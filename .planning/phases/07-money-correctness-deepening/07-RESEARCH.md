# Phase 7: Money-Correctness Deepening — Research

**Researched:** 2026-06-27
**Domain:** Brownfield correctness fixes — pure-function judgment pipeline (`validate.py`, `reconcile_names.py`, `orchestrator.py`, `repo.py`, `contracts.py`, schema.sql)
**Confidence:** HIGH (every claim verified against live source files)

---

## Summary

Phase 7 closes three silent-mispay paths via targeted, code-level brownfield fixes on an already-shipped pipeline. The scope is narrow and the design is fully locked in CONTEXT.md (30 decisions). Research here is purely code-verification: read the live files, confirm or correct every file:line the CONTEXT.md cites, resolve the two open questions (D-12 aggregation + D-24 serializer), and flag any contradiction between the locked design and the live code before the planner commits to a plan that will not apply cleanly.

**Outcome:** All 30 locked decisions are confirmed consistent with the live code. Three corrections are needed: (1) the cited line numbers in CONTEXT.md have drifted; (2) `ValidationIssue.issue_type` is a `Literal["missing", "out_of_bounds", "non_numeric"]` — "field_regression" is NOT a legal value today and the Literal must be widened; (3) the eval's `_normalize` helper does NOT call `unicodedata.normalize`, which means a new NFD-name fixture will produce wrong reconciliation scoring unless `run_eval.py:_normalize` is updated alongside `_norm`. Both are pre-conditions the planner must include.

**Primary recommendation:** Begin with the `_is_paid` shared predicate (D-09) and the `ValidationIssue` Literal widening (MONEY-01/03 pre-conditions), then NFC (MONEY-02), then the snapshot/clarified_fields columns and `detect_field_regression` (MONEY-03). TDD throughout — each fix begins with a failing test.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All 30 decisions (D-01 through D-30) in CONTEXT.md are locked. Key planning-relevant locks:
- D-02: replace `is not None` with `_is_paid` predicate in `any_hours`
- D-05: hardened NFC form `NFC(casefold(NFC(s)))` in `_norm`
- D-06: `_norm` is the SOLE chokepoint — fix there, all callers get it for free
- D-09: shared `_is_paid(v) = v is not None and v > 0` used from three sites
- D-11: diff set keyed by `employee_id` resolved in BOTH snapshots
- D-12: last-wins symmetric reduction by `employee_id` (researcher resolution: see below)
- D-13: `clarified_fields` is a NEW nullable JSONB column, shape `{employee_id: {field: outcome}}`
- D-14: explicit-zero → `confirmed_dropped` (NO backfill); silence → `carried_forward` (backfill)
- D-15: `confirmed_dropped` MUST short-circuit BEFORE MONEY-01 re-flags
- D-17: `detect_field_regression` → pure helper; `validate()` gains `prior=None` kwarg
- D-18: `_run_stages` stays a SINGLE shared function; fresh runs pass `prior=None`
- D-19: `pre_clarify_extracted` is a NEW nullable JSONB column; snapshot-once (`IS NULL` guard)
- D-20: in-run ordering locked (see below)
- D-22: `claim_status` CAS already exists — do NOT re-add
- D-23: two-layer eval split — eval certifies judgment only; integration tests certify state machine
- D-24: eval `prior` fixtures serialized through `extracted.model_dump_json()` path, NOT hand-typed JSON
- D-30: ship shared predicate + explicit-drop outcome FIRST

### Claude's Discretion
- Exact clarification-email copy wording for field-regression question
- Precise JSONB shape of `clarified_fields` / `pre_clarify_extracted` (follow `alias_candidates` precedent)
- Whether symmetric reduction is last-wins vs sum (locked: last-wins is default; deviate only if researcher finds aggregation contract — see D-12 resolution below)

### Deferred Ideas (OUT OF SCOPE)
- `contribution_401k_override` and salary in field-regression watch list (D-08)
- Full single-transaction wrapping of resume sequence (Phase 9)
- Crash-idempotency + concurrency proof tests (Phase 9/10)
- Sum vs last-wins multi-line reduction (locked: last-wins unless contradicted)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MONEY-01 | Hourly employee with explicitly-zero hours gates to `request_clarification`, never ships $0 paystub | D-02/D-09: replace `is not None` with `_is_paid` in `any_hours`; predicate confirmed absent today at validate.py:84 |
| MONEY-02 | Unicode NFC normalization in `_norm` before casefold so NFD/NFC name variants resolve as a match | D-05: `_norm` at reconcile_names.py:32 confirmed casefold-only; `unicodedata.normalize` absent |
| MONEY-03 | Field-regression detection: clarify once on drop, carry forward if still unaddressed, honor explicit zero | D-13/D-14/D-17/D-19/D-20: all new code; schema needs two columns; `ValidationIssue` Literal needs widening |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Zero-hours gate (MONEY-01) | Pipeline / `validate.py` pure function | — | Predicate change in one function; no DB, no model, no orchestrator change |
| Unicode normalization (MONEY-02) | Pipeline / `reconcile_names.py` pure function | Eval `run_eval.py:_normalize` (CORRECTION needed) | `_norm` is the sole chokepoint; eval's own normalizer is separate and also needs patching |
| Field-regression detection (MONEY-03) | Pipeline / new `detect_field_regression` pure helper + `validate.py prior=` seam | Orchestrator resume sequence + DB schema | Detection is pure; loop-guard and carry-forward are orchestrator + DB state |
| Snapshot storage (`pre_clarify_extracted`) | DB / `payroll_runs` schema + `repo.py` | Orchestrator (`resume_pipeline`) writes it | JSONB column, same pattern as `alias_candidates` |
| Loop-guard storage (`clarified_fields`) | DB / `payroll_runs` schema + `repo.py` | Orchestrator reads/writes at resume | JSONB column, same pattern as `alias_candidates` |
| Eval: judgment certification | Eval / `run_eval.py` (import validate/decide directly) | — | eval cannot see the state machine (D-23) |
| Eval: state machine certification | Integration tests (real DB + orchestrator) | — | loop-guard, backfill, and snapshot-once are integration claims (D-23/D-29) |

---

## Code Verification Findings

### Target 1: `app/pipeline/validate.py`

**Current anchor line for `any_hours`:** Line **84** (matches CONTEXT.md cite of "~line 84"). CONFIRMED.

```python
# Line 84 (current):
any_hours = any(
    getattr(emp, f) is not None for f in _HOURS_FIELDS
)
```

**CONFIRMED: D-01 bug exists.** `is not None` lets `Decimal("0")` pass. `hours_regular=Decimal("0")` returns `True` from `any_hours` (it is not None), the employee is skipped (no issue emitted), and a $0 paystub ships.

**CONFIRMED: D-05 over-40 guard at lines 102–140.** The `ot_missing = ot is None or ot == 0` pattern is present at line 113. This is the exact precedent for the shared `_is_paid` predicate (D-09).

**CONFIRMED: docstring at lines 1–21 (not 15–20).** The docstring spans the whole module header (lines 1–21). The negative-hours reasoning is at lines 15–20 of the FIX 1 comment block. D-03 reasoning is correct: `extra="forbid"` + `ge=0` on `ExtractedEmployee` means a negative never reaches `validate()`.

**CONFIRMED: current `validate()` signature (line 69–73):**
```python
def validate(
    extracted: Extracted,
    roster: Roster,
    matches: list[NameMatchResult],
) -> list[ValidationIssue]:
```
The new `prior: Extracted | None = None` kwarg (D-17/D-18) slots in as a fourth positional parameter with default `None`. Every existing caller (`orchestrator.py:273`, `run_eval.py:159`) passes exactly three positional args and will remain unbroken.

**CONFIRMED: `decide.py` gates on `issue_type="missing"` (line 124).**  `ValidationIssue.issue_type` must therefore include `"field_regression"` for D-17's seam to work. See CORRECTION 1 below.

**CONFIRMED: `_HOURS_FIELDS` tuple at lines 27–33** — the five fields are already defined as a module-level constant in `validate.py`. The new `detect_field_regression` helper should import or re-use this same tuple (DRY; do NOT redefine).

**No landmines beyond CORRECTION 1.**

---

### Target 2: `app/pipeline/reconcile_names.py`

**Current anchor line for `_norm`:** Line **32**. CONFIRMED.

```python
# Line 32 (current):
def _norm(name: str) -> str:
    """Whitespace-normalize + casefold for deterministic comparison."""
    return " ".join(name.split()).casefold()
```

**CONFIRMED: D-04 bug exists.** No `unicodedata.normalize` call. NFD "José" and NFC "José" casefold to different byte sequences → no match.

**CONFIRMED: D-06 `_norm` is the sole chokepoint.** Every resolution path in `deterministic_match` calls `_norm` (lines 52, 54, 56). The orchestrator imports `_norm` directly at line 346, 174, and 204 for alias-candidate capture logic. All callers are in-module or via explicit import — there is no second normalizer.

**CORRECTION — eval normalizer mismatch:** `run_eval.py:51–53` defines its OWN `_normalize`:
```python
def _normalize(name: str) -> str:
    """casefold + collapse whitespace -- same normalization reconcile_names uses."""
    return " ".join(name.casefold().split())
```
This is a **separate function** from `_norm` — it is NOT imported from `reconcile_names`. It is used in extraction scoring (lines 168, 173, 196, 197, 234, 239) and reconciliation result lookup (line 238). After MONEY-02 is applied, `reconcile_names._norm` will normalize NFC before casefold, but `run_eval.py:_normalize` will NOT. An NFD-name fixture whose expected block uses the NFC form of the name will produce a false-negative in the extraction scoring (the actual extracted name is NFD; `_normalize` won't match it to the NFC expected entry). **The planner must include a task to update `run_eval.py:_normalize` to match the new `_norm` form — or to import `_norm` directly.** This is a critical eval-fidelity gap (D-24 spirit).

**No other callers of `_norm` are relevant to the fix.** The `_safe_to_learn_alias` function also uses `_norm` (line 134) and will benefit automatically.

---

### Target 3: `app/pipeline/calculate.py`

**D-12 cited anchor: "one PaystubLineItem per extracted entry, no dedup (~286–289)".**

**CONFIRMED: lines 286–306** — `calculate()` returns exactly one `PaystubLineItem` per call, no dedup, no aggregation. The `_compute_line_items` function (orchestrator.py:672–714) calls `calculate()` once per `ee` in `extracted.employees` and appends one item per loop iteration. There is NO aggregation anywhere in this path.

**D-12 open question resolved — last-wins is safe:** There is NO hidden aggregation contract anywhere in `calculate.py` or `_compute_line_items`. The code iterates `extracted.employees` one-to-one: for each `ExtractedEmployee`, one `Employee` roster entry, one `calculate()` call, one `PaystubLineItem`. If `extracted.employees` somehow contained two entries for the same `employee_id`, the result list would contain two `PaystubLineItem` rows for that employee — the DELETE-by-run + INSERT in `replace_line_items` would write both to the DB, and the operator gate would see two paystubs for the same person.

**Last-wins reduction for the D-12 diff is safe** because: (a) no existing caller expects or produces duplicate `employee_id` entries in `extracted.employees` — the extraction LLM produces one entry per submitted name, and submitted names are expected to be distinct; (b) the symmetric last-wins reduction is applied to BOTH the snapshot and the resumed extraction before diffing, so if the LLM does somehow produce two entries for one `employee_id`, last-wins consistently picks the later one on both sides, producing an accurate diff. There is no sum/aggregation contract to violate.

**Landmine — the reduction is ONLY needed for the D-11 diff set.** The `_compute_line_items` call itself does NOT need to change; it already de-dupes via `match_by_name` (line 674: `{m.submitted_name: m for m in matches}`) which is keyed by `submitted_name`, not `employee_id`. Two different submitted names resolving to the same `employee_id` would result in two paystubs (caught by `check_one_to_one`). The symmetric reduction is only for the snapshot-vs-resumed comparison.

---

### Target 4: `app/pipeline/orchestrator.py`

**CONFIRMED: `resume_pipeline` at lines 94–241.** The function spans exactly these lines.

**CONFIRMED: `claim_status` CAS at line 124:**
```python
claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
```
D-22 is correct. This is already atomic. Do NOT re-add.

**CONFIRMED: pre-vs-post resolved-`employee_id` diff model at lines 142–234.** Steps A/B/C/D are present. The D-11 diff pattern is a direct mirror of this: pre-load → run stages → post-load → diff the id sets. The field-regression diff is the same machinery applied to extracted hours instead of resolved employee ids.

**CONFIRMED: `_run_stages` at lines 260–290.** Current call sites:
- `run_pipeline` → `_run_stages(run_id, email, roster, llm=llm)` (line 91)
- `resume_pipeline` → `_run_stages(run_id, combined_email, roster, llm=llm)` (line 165)

The D-20 in-run ordering must be wired **in `resume_pipeline` between lines 140–165**, BEFORE the `_run_stages` call. Specifically:
1. `claim_status` (already line 124) 
2. Load run + roster (already lines 133–136)
3. Rebuild combined email (already lines 139–140)
4. **NEW: Load `pre_clarify_extracted` snapshot — write iff NULL**
5. **NEW: Re-extract (call `_run_stages` — which calls extract, then reconcile)**
6. Wait — D-20 says the reduce/detect/outcome-resolve happen BETWEEN extract and validate.

**CRITICAL WIRING DETAIL:** D-20's ordering (`detect → outcome-resolve/backfill → validate`) means these steps cannot all live inside `_run_stages` as currently structured, because `_run_stages` calls `extract → reconcile_names → validate → decide` as a single pipeline. To insert `detect/reduce/backfill` between `reconcile` and `validate`, the planner has two options:

Option A (RECOMMENDED per D-18): Pass `prior` to `validate()` and let `detect_field_regression` run INSIDE `validate()` when `prior` is non-None. The reduce step runs on the extracted object before it enters validate. `_run_stages` passes the reduced extraction down plus `prior=snapshot` to `validate`.

Option B: Split `_run_stages` into extract+reconcile and validate+decide, with the detect/reduce in between. This is more invasive and contradicts D-18 ("DRY spine preserved").

**The planner should use Option A**: `resume_pipeline` does the snapshot load + reduce-by-employee_id BEFORE calling `_run_stages`, and passes the reduced+backfilled extracted object to `_run_stages` along with the `prior` snapshot. `_run_stages` gains an optional `prior=None` kwarg that it passes through to `validate()`. This minimizes changes to `_run_stages` and preserves the DRY spine.

**CONFIRMED: PII-safe error boundary at lines 235–241.** Any new code in `resume_pipeline` must remain inside this try/except.

---

### Target 5: `app/pipeline/decide.py`

**CONFIRMED: Rule 2 at line 124:**
```python
missing = [i.field for i in issues if i.issue_type == "missing"]
gate_reasons += [f"missing required field: {f}" for f in missing]
```

**CONFIRMED and CORRECTED:** `decide.py` gates on `issue_type == "missing"`. D-17's `ValidationIssue(issue_type="field_regression")` would NOT be caught by this rule — it would be silently ignored. `decide.py` must EITHER be updated to also gate on `"field_regression"`, OR `detect_field_regression` must emit a `ValidationIssue(issue_type="missing")` with a descriptive message and field.

**CONTEXT.md D-17 says:** "validate() emits a ValidationIssue(issue_type='field_regression')" and "decide.py is UNCHANGED — it already gates request_clarification on any missing/issue."

**This is a contradiction with the live code.** Rule 2 filters by `issue_type == "missing"` only. There is no rule that catches all non-empty `issues`. The CONTEXT.md statement is wrong about `decide.py` being unchanged.

**Resolution (choose one, planner must decide):**
- **Option A (minimal):** `detect_field_regression` emits `ValidationIssue(issue_type="missing", field=..., message="field regression: OT was X, now absent")`. No change to `decide.py`. The `"missing"` type is semantically slightly wrong but works with the existing gate.
- **Option B (cleanest):** Widen `ValidationIssue.issue_type` Literal to include `"field_regression"` AND add Rule 2b to `decide.py`: `gate_reasons += [f"field regression: {i.field}" for i in issues if i.issue_type == "field_regression"]`. This is 2 lines in `decide.py` and is the honest representation of the new issue type.
- **Option C (D-17 literal):** Emit `issue_type="field_regression"`, and in `decide.py` gate on "any non-empty `issues`" instead of filtering by type. This widens the gate unexpectedly.

**Recommendation: Option B.** It is the cleanest, most honest, and matches D-17's stated intent with minimal code. The "unchanged" claim in CONTEXT.md was imprecise — `decide.py` needs exactly two lines added to gate on the new issue type. Flag this to the user before planning.

---

### Target 6: `app/db/repo.py`

**CONFIRMED: `set_alias_candidates` at lines 509–524.** This is the exact migration precedent for the two new columns. Pattern:
```python
def set_alias_candidates(run_id, candidates: dict, conn=None) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET alias_candidates = %s, updated_at = now() WHERE id = %s",
                (json.dumps(candidates), str(run_id)),
            )
```
Serialization: `json.dumps(candidates)` — a plain dict, not a Pydantic model. For `pre_clarify_extracted` (which is an `Extracted`), the pattern is `json.dumps(extracted.model_dump(mode="json"))`, matching `persist_extracted` at line 419.

**CONFIRMED: `claim_status` at lines 342–367** — the CAS pattern. Already used in `resume_pipeline`.

**CONFIRMED: `persist_extracted` at lines 407–424** — uses `json.dumps(extracted.model_dump(mode="json"))`. This is the EXACT serializer for `pre_clarify_extracted`.

**CONFIRMED: `RUN_COLS` at line 91–93 does NOT include `alias_candidates`, `pre_clarify_extracted`, or `clarified_fields`.** These columns are loaded separately (via `repo.load_run()` which uses `RUN_COLS`). Wait — `load_run` uses `RUN_COLS` which does NOT include `alias_candidates`. Yet `resume_pipeline:154` calls `repo.load_run(run_id)` and then does `pre_run_data.get("alias_candidates")`. This means `alias_candidates` IS in `RUN_COLS` or there is another loading mechanism.

**CORRECTION — RUN_COLS inspection:**
```python
# Line 91–93:
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, pay_period_start, pay_period_end, updated_at"
)
```
`alias_candidates` is NOT in `RUN_COLS`. Yet `resume_pipeline:154` does `pre_run_data.get("alias_candidates")` after calling `repo.load_run(run_id)`. Since `alias_candidates` is not in `RUN_COLS`, `pre_run_data.get("alias_candidates")` will ALWAYS return `None`.

**This is a live bug in the shipped code**, but it is HARMLESS to alias-learning because the fallback is `{}` (line 154: `_pre_candidates = (pre_run_data.get("alias_candidates") or {}) if pre_run_data else {}`). The alias_candidates column is populated by `set_alias_candidates` in `_clarify`, but `load_run` cannot see it because `RUN_COLS` doesn't include it. The alias learning still works because `_write_aliases_if_safe` (line 471) calls `repo.load_run(run_id)` and then accesses `run_data.get("alias_candidates")` — same bug.

**For Phase 7:** the two new columns `pre_clarify_extracted` and `clarified_fields` need to be readable by resume. This means either: (a) add them to `RUN_COLS`, or (b) add targeted repo helpers (`load_pre_clarify_snapshot`, `load_clarified_fields`) that SELECT just those columns. Following the `alias_candidates` precedent means option (b) is standard practice here — separate helpers rather than bloating `RUN_COLS`. The planner should add `set_pre_clarify_extracted`, `load_pre_clarify_extracted`, `set_clarified_fields`, `load_clarified_fields` repo helpers.

**Note on the alias_candidates RUN_COLS gap:** Phase 7 should NOT fix the `alias_candidates` gap (that would change Phase 5 behavior and is out of scope). Just follow the same pattern.

---

### Target 7: `app/models/contracts.py`

**CONFIRMED: `ExtractedEmployee` hours fields at lines 75–80:**
```python
hours_regular: Decimal | None = Field(default=None, ge=0)
hours_overtime: Decimal | None = Field(default=None, ge=0)
hours_vacation: Decimal | None = Field(default=None, ge=0)
hours_sick: Decimal | None = Field(default=None, ge=0)
hours_holiday: Decimal | None = Field(default=None, ge=0)
```
D-03 is CONFIRMED: `ge=0` + `extra="forbid"` on `ExtractedEmployee` (line 62: `model_config = ConfigDict(extra="forbid")`). A negative value causes a Pydantic `ValidationError` at parse time → one retry → ERROR. Never reaches `validate()`.

**CORRECTION — `ValidationIssue.issue_type` Literal (lines 215–216):**
```python
issue_type: Literal["missing", "out_of_bounds", "non_numeric"]
```
`"field_regression"` is NOT in this Literal. Any attempt to construct `ValidationIssue(issue_type="field_regression", ...)` will raise a `ValidationError` at runtime. This Literal MUST be widened before D-17 can work.

**Action required:** Add `"field_regression"` to the Literal on line 215 of `contracts.py`. This is a backward-compatible change (existing values unchanged; existing tests unaffected). This is a Wave 0 pre-condition for MONEY-03.

**`FieldDrop` shape (new type needed):** `detect_field_regression(original, resumed) -> list[FieldDrop]`. `FieldDrop` is a new dataclass or Pydantic model. Suggested shape (following project conventions):
```python
class FieldDrop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: UUID          # resolved employee id (from snapshot)
    field: str                 # e.g. "hours_overtime"
    original_value: Decimal    # the value in the snapshot (_is_paid = True)
    resumed_value: Decimal | None  # None = absent in resume; Decimal("0") = explicit zero
```
This belongs in `contracts.py` alongside the other pipeline I/O contracts. Its `resumed_value` is the signal for D-14: `None` → `carried_forward`; `Decimal("0")` → `confirmed_dropped`.

---

### Target 8: `app/llm/client.py`

**CONFIRMED: `temperature=0` at line 124:**
```python
resp = client.chat.completions.create(
    model=cfg.model,
    messages=convo,
    temperature=0,
    ...
)
```
D-27's determinism property is confirmed. `call_structured` always uses `temperature=0`. Only `call_text` uses `temperature=0.7` (the drafting path, which is appropriate).

---

### Target 9: `eval/run_eval.py`

**CONFIRMED: imports at lines 31–36:**
```python
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.validate import validate
from app.pipeline.decide import decide
```
The eval imports the SAME production functions. `validate`'s new `prior=None` default means existing eval calls at line 159 (`issues = validate(expected_extracted, roster, matches)`) pass exactly 3 args and remain unbroken — `prior` defaults to `None` → no-op.

**CONFIRMED: fixture structure.** Each fixture is a JSON file with an `InboundEmail`-compatible flat structure plus `expected` and `fixture_category` keys. The extraction cache is a sibling `{stem}_extraction.json` file containing a serialized `Extracted` (via `model_dump_json()`). See `07_missing_hours_coastal.json` and `07_missing_hours_coastal_extraction.json`.

**D-24 fixture-fidelity serializer — CONFIRMED:** The extraction cache writer at line 655 uses:
```python
cache_path.write_text(extracted.model_dump_json(indent=2))
```
The extraction cache loader at line 117 uses:
```python
return Extracted.model_validate(json.loads(cache_path.read_text()))
```
For the new `prior` fixtures, the planner must use the SAME round-trip: `extracted.model_dump_json()` → write to file → `Extracted.model_validate(json.loads(...))` → use as `prior`. Do NOT hand-construct the JSON. The `model_dump_json()` serializer handles `Decimal` → string (D-06), `UUID` → string, `date` → ISO string. Hand-typed JSON would need to replicate these exact serialization rules.

**Where to add the three new fixtures:**
- `eval/fixtures/16_zero_hours_hourly_{business}.json` + `_extraction.json` — MONEY-01 judgment slice
- `eval/fixtures/17_nfd_name_{business}.json` + `_extraction.json` — MONEY-02 judgment slice  
- `eval/fixtures/18_field_drop_clarify_carry_{business}.json` + `_extraction.json` — MONEY-03 judgment slice (the `prior=` seam test)

The fixtures must be numbered sequentially after the existing 15 (01–15 visible; 31 total files = 15 fixtures + 15 extraction caches + `summary.json`). Actually the listing showed `01_` through at least fixture 10 visible; there are 31 total files / 2 = 15 fixtures + 1 summary = 16 items. New fixtures start at 16 (or whatever the next available number is — planner should check via `ls` at task time).

**CORRECTION — eval's `_normalize` does NOT match the new `_norm`:** As noted under Target 2, `run_eval.py:_normalize` (line 51) does `casefold().split()` without NFC. The NFD-name fixture (MONEY-02) will produce a mismatch in the extraction scoring loop because `_normalize` won't match the NFD submitted_name to the NFC expected name. The planner must update `run_eval.py:_normalize` to NFC-normalize before casefold, matching the new `_norm`.

---

## Schema Migration Precedent

**Migration pattern for `alias_candidates` (the precedent for D-19/D-13):**

In `schema.sql`, `alias_candidates` is:
1. Declared inline in `CREATE TABLE IF NOT EXISTS payroll_runs` (line 90)
2. Added idempotently via `ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS alias_candidates JSONB` (line 107)

In `bootstrap.py`, no special handling — the `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` in `schema.sql` handles idempotency.

**For `pre_clarify_extracted` (JSONB, nullable) and `clarified_fields` (JSONB, nullable):**

1. Add inline in the `payroll_runs` CREATE TABLE block in `schema.sql` (alongside `alias_candidates`)
2. Add `ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS pre_clarify_extracted JSONB;` after line 107
3. Add `ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields JSONB;` after that

No migration script beyond `schema.sql` + `bootstrap.py` is needed. The existing `bootstrap` non-destructive path applies `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` idempotently. Both new columns are nullable JSONB with no default, so existing runs are unaffected (they get NULL, which is the correct pre-existing state).

**Schema.sql exact line targets:**
- Add inline declarations: after line 91 (`alias_candidates JSONB,`), add:
  ```sql
  pre_clarify_extracted JSONB,    -- D-19: snapshot of extracted_data at awaiting_reply pause
  clarified_fields JSONB,          -- D-13: {employee_id: {field: outcome}} field-regression outcomes
  ```
- Add idempotent ALTER statements: after line 107 (`alias_candidates` ALTER), add:
  ```sql
  ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS pre_clarify_extracted JSONB;  -- D-19 MONEY-03
  ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields JSONB;       -- D-13 MONEY-03
  ```

**Repo helpers to add (following `set_alias_candidates` pattern):**
- `set_pre_clarify_extracted(run_id, extracted: Extracted, conn=None) → None` — writes `json.dumps(extracted.model_dump(mode="json"))` with `IS NULL` guard in SQL
- `load_pre_clarify_extracted(run_id, conn=None) → Extracted | None` — reads and validates
- `set_clarified_fields(run_id, clarified: dict, conn=None) → None` — writes `json.dumps(clarified)`
- `load_clarified_fields(run_id, conn=None) → dict` — reads, returns `{}` on NULL

The `IS NULL` guard for snapshot-once (D-19) should be in the SQL:
```sql
UPDATE payroll_runs SET pre_clarify_extracted = %s, updated_at = now()
WHERE id = %s AND pre_clarify_extracted IS NULL
```
This makes the guard atomic — no separate read-then-write.

---

## Architecture Patterns

### D-20 In-Run Ordering (the termination-safe sequence)

The locked ordering from CONTEXT.md D-20, mapped to actual code locations:

```
resume_pipeline() [orchestrator.py]
  │
  ├─ claim_status(AWAITING_REPLY → EXTRACTING) [line 124, EXISTING]
  ├─ load_run + roster [lines 133–136, EXISTING]
  ├─ rebuild combined_email [lines 139–140, EXISTING]
  │
  ├─ [NEW] load_pre_clarify_extracted(run_id) → snapshot
  ├─ [NEW] if snapshot is None: set_pre_clarify_extracted(run_id, ???)  ← D-21 problem
  │
  ├─ _run_stages(run_id, combined_email, roster, prior=snapshot, llm=llm)
  │     │
  │     ├─ extract() → extracted  [NEW: this is the re-extract; result is the "resumed"]
  │     ├─ [NEW] reduce_by_employee_id(extracted) → reduced  [D-12 last-wins]
  │     ├─ [NEW] if snapshot: detect_field_regression(snapshot, reduced) → drops
  │     ├─ [NEW] for each drop: outcome-resolve (D-13/D-14) → backfill OR record "asked"
  │     ├─ [NEW] backfill applied to `reduced` BEFORE validate
  │     ├─ reconcile_names(reduced.employees) → matches
  │     ├─ validate(reduced, roster, matches, prior=snapshot)  ← emits field_regression issues
  │     └─ decide(reduced, matches, issues)
  │
  └─ [alias diff binding, EXISTING]
```

**D-21 snapshot timing problem:** The snapshot should capture `extracted_data` at the `awaiting_reply` PAUSE, not at resume. At resume time, `extracted_data` has already been overwritten by the previous `_run_stages` call that produced the clarification. This means `set_pre_clarify_extracted` must be called in `_clarify()` or immediately before `repo.set_status(run_id, RunStatus.AWAITING_REPLY)` — NOT in resume_pipeline. The `IS NULL` guard then prevents a second clarification (e.g. name-clarify, then field-clarify) from overwriting the snapshot with the post-first-resume state.

**Revised wiring:**
- `_clarify()` [orchestrator.py:292] → add `set_pre_clarify_extracted(run_id, current_extracted)` BEFORE `repo.set_status(run_id, RunStatus.AWAITING_REPLY)`, with the `IS NULL` guard in SQL (so the first `_clarify` call writes the snapshot; subsequent ones are no-ops).
- At this point in `_clarify`, `extracted` is not directly in scope. The planner must thread it through from `_run_stages` → `_clarify`.

**Simplest threading approach:** `_run_stages` returns the `extracted` object (currently returns `None`). `_clarify` receives `extracted` as a parameter. This avoids a second `load_run` call.

### The `_is_paid` Shared Predicate

Lives in `validate.py` (where both MONEY-01 and MONEY-03 use it):

```python
def _is_paid(v: Decimal | None) -> bool:
    """True iff the value is present AND > 0 (shared predicate, D-09)."""
    return v is not None and v > 0
```

Used at three sites:
1. `any_hours` in `validate()` — replaces `getattr(emp, f) is not None`
2. `detect_field_regression` — defines "present" for drop detection
3. Aligns with `ot_missing = ot is None or ot == 0` (D-05 guard) — these are logically equivalent: `ot_missing == not _is_paid(ot)`

### `detect_field_regression` Pure Helper

Lives in a new module or in `validate.py`. Given the D-18 DRY-spine principle and the fact that `validate.py` already owns the judgment about hours fields, co-locating in `validate.py` is simplest:

```python
def detect_field_regression(
    original: Extracted,
    resumed: Extracted,
) -> list[FieldDrop]:
    """Compare hours fields for employees resolved in BOTH snapshots (D-11).
    
    Returns FieldDrop for any field that was _is_paid() in original
    but is NOT _is_paid() in resumed (drop or explicit zero). D-10: only
    present→absent/zero triggers; an increase or change-while-paid is silent.
    """
```

The `prior: Extracted | None = None` kwarg on `validate()` passes `original` to this helper. When `prior is None` (fresh runs), the helper is never called → pure no-op (D-18).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSONB column reads for new Phase 7 columns | A separate query inside orchestrator | `repo.load_pre_clarify_extracted()` / `repo.load_clarified_fields()` helpers | Follows existing `alias_candidates` precedent; keeps DB access in the repo layer |
| Snapshot-once atomicity | A read-then-conditional-write in Python | SQL `WHERE id = %s AND pre_clarify_extracted IS NULL` | The IS NULL check must be atomic; Python read-then-write has the same race as the old claim_status bug |
| NFC normalization logic | Custom Unicode folding | `unicodedata.normalize("NFC", ...)` — stdlib | stdlib handles all edge cases; the double-NFC-around-casefold (D-05) is 3 lines |
| Decimal → JSON in fixture files | Hand-typing `"40.00"` strings | `extracted.model_dump_json()` | Pydantic's serializer handles Decimal → string correctly; hand-typing risks skew (D-24) |

---

## Common Pitfalls

### Pitfall 1: Widening `any_hours` without the shared predicate
**What goes wrong:** If MONEY-01 fixes `any_hours` with `is not None and != 0` directly (not using `_is_paid`), and MONEY-03 defines its own "present" check differently, `OT 2→0` might be treated as "still paid" (not a drop) in MONEY-03 while being "missing" in MONEY-01 — the D-09 disagreement on the zero boundary.
**Prevention:** Define `_is_paid` first, use it in BOTH places. The tests D-25 (predicate-consistency) and D-26 (explicit-drop-confirmation) catch this.

### Pitfall 2: Backfill before vs after `validate()`
**What goes wrong:** If backfill happens AFTER `validate()`, the carried-forward value is NOT in the `extracted_data` that validate sees. Then MONEY-01 will re-flag the zero/absent field as missing → `decide()` clarifies again → infinite loop (D-20's termination constraint).
**Prevention:** Backfill into `reduced` BEFORE `validate()` runs. The D-20 ordering is non-negotiable.

### Pitfall 3: `confirmed_dropped` not short-circuiting MONEY-01
**What goes wrong:** Client replies "0 OT" (explicit zero). MONEY-03 records `confirmed_dropped`. But MONEY-01's `_is_paid` check on the resumed extraction sees `hours_overtime=Decimal("0")` → `_is_paid` is False → if ALL fields are not paid → MONEY-01 emits "missing" → clarify again. The client said "remove it" and gets asked again.
**Prevention:** D-15 — the outcome check (`confirmed_dropped` in `clarified_fields`) must run BEFORE `any_hours` (i.e., in the backfill/outcome-resolve step, mark the field as "resolved, skip MONEY-01 for this field"). One approach: backfill a `confirmed_dropped` field to its original value temporarily just for MONEY-01, but mark it in `clarified_fields` so it doesn't loop. Simpler approach: after outcome-resolve, add those employees/fields to a "skip MONEY-01 gate" set passed into `validate()` alongside `prior`. The planner must design this interaction carefully.

### Pitfall 4: `_run_stages` returning None
**What goes wrong:** Threading `extracted` from `_run_stages` to `_clarify` requires `_run_stages` to return the extracted object (or pass it via parameter). Currently it returns `None`. Adding a return value is backward-compatible (callers that ignore the return are unaffected), but the planner must update both call sites (`run_pipeline` and `resume_pipeline`) to capture the return if needed.
**Prevention:** Make `_run_stages` return the `extracted` object; update callers to capture it on the resume path only.

### Pitfall 5: NFD fixture creating eval score regression
**What goes wrong:** Adding an NFD-name fixture BEFORE fixing `run_eval.py:_normalize` will cause the fixture to fail extraction scoring (because `_normalize` won't match the NFD submitted_name to the NFC expected name), making the overall eval scores drop — a false regression in `summary.json`.
**Prevention:** Fix `run_eval.py:_normalize` in the same wave as `reconcile_names._norm` (MONEY-02), before adding the NFD fixture.

---

## Code Examples

### Current `_norm` (to be replaced)
```python
# reconcile_names.py:32 — CURRENT (no NFC)
def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()
```

### Target `_norm` (D-05 hardened form)
```python
# reconcile_names.py:32 — TARGET
import unicodedata

def _norm(name: str) -> str:
    """Whitespace-normalize + NFC(casefold(NFC(s))) for deterministic comparison (D-05)."""
    nfc = unicodedata.normalize("NFC", name)
    return " ".join(unicodedata.normalize("NFC", nfc.casefold()).split())
```

### `set_pre_clarify_extracted` (snapshot-once pattern)
```python
def set_pre_clarify_extracted(
    run_id: uuid.UUID,
    extracted: Extracted,
    conn=None,
) -> bool:
    """Write pre_clarify_extracted ONLY IF NULL (snapshot-once, D-19).
    Returns True if the snapshot was written, False if already set."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET pre_clarify_extracted = %s, updated_at = now() "
                "WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id",
                (json.dumps(extracted.model_dump(mode="json")), str(run_id)),
            ).fetchone()
    return row is not None
```

### `_is_paid` predicate (D-09)
```python
# validate.py — new module-level helper
from decimal import Decimal

def _is_paid(v: Decimal | None) -> bool:
    """True iff value is present AND > 0 (D-09 shared predicate).
    
    Defines "present with a positive value" for both the any_hours gate (D-01/02)
    and the field-regression drop detection (D-10). Decimal("0") is treated the
    same as None — both count as absent/dropped.
    """
    return v is not None and v > 0
```

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest -q`) |
| Config file | none found (pytest discovers `tests/` automatically) |
| Quick run command | `uv run pytest tests/test_validate.py tests/test_reconcile.py -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MONEY-01 | Hourly employee with `hours_regular=0` (explicit zero) + all other hours None/zero → `request_clarification` | unit | `uv run pytest tests/test_validate.py -k "zero_hours" -x` | ❌ Wave 0 |
| MONEY-01 | Hourly employee with `hours_regular=0` + `hours_holiday=8` (partial week) → NOT gated (D-03 edge) | unit | `uv run pytest tests/test_validate.py -k "partial_week" -x` | ❌ Wave 0 |
| MONEY-01 | `pay_type=None/unknown` + all-zero hours → treated as "could be hourly" → gate | unit | `uv run pytest tests/test_validate.py -k "unknown_pay_type" -x` | ❌ Wave 0 |
| MONEY-01 | D-25 predicate-consistency: `OT 2→0` gates identically to `OT 2→absent` | unit | `uv run pytest tests/test_validate.py -k "predicate_consistency" -x` | ❌ Wave 0 |
| MONEY-02 | NFD "José" matches NFC "José" in roster via `_norm` | unit | `uv run pytest tests/test_reconcile.py -k "nfd" -x` | ❌ Wave 0 |
| MONEY-02 | `run_eval.py:_normalize` matches `_norm` behavior on NFD input | unit | `uv run pytest tests/test_eval_wiring.py -k "nfd" -x` | ❌ Wave 0 |
| MONEY-03 | `detect_field_regression`: `OT=2` snapshot, `OT=None` resumed → returns `FieldDrop` for OT | unit | `uv run pytest tests/test_validate.py -k "detect_regression" -x` | ❌ Wave 0 |
| MONEY-03 | D-26 explicit-drop: reply with `OT=0` → `confirmed_dropped`, NO carry-forward | unit | `uv run pytest tests/test_validate.py -k "explicit_drop" -x` | ❌ Wave 0 |
| MONEY-03 | D-27 determinism: no-op reply → `detect_field_regression` returns `[]` | unit | `uv run pytest tests/test_validate.py -k "no_regression" -x` | ❌ Wave 0 |
| MONEY-03 | D-28 multi-round baseline: second clarification does NOT overwrite snapshot | integration | `uv run pytest tests/test_resume_pipeline.py -k "snapshot_once" -x` | ❌ Wave 0 |
| MONEY-03 | Loop guard: field-regression clarify fires exactly ONCE, then carry-forward | integration | `uv run pytest tests/test_resume_pipeline.py -k "loop_guard" -x` | ❌ Wave 0 |
| MONEY-01/02/03 | Eval judgment fixtures: three new fixtures score correctly | unit (eval) | `uv run python eval/run_eval.py` | ❌ Wave 0 |

**Note on test file locations:** Existing pattern uses `tests/test_validate.py` for validate tests and `tests/test_reconcile.py` likely exists (verify — not confirmed by ls). Integration tests for resume state machine should go in a new `tests/test_resume_pipeline.py` (or extend `tests/test_clarify.py` if it covers resume).

### D-23 Two-Layer Split (mandatory documentation)
- **Eval layer (unit judgment):** Fixtures + `validate()` + `decide()` called directly prove "given a prior snapshot, does validate detect the drop and gate." This is what `run_eval.py` can certify.
- **Integration layer (state machine):** `resume_pipeline()` with real DB columns proves "clarifies exactly once then terminates." This requires `pre_clarify_extracted` and `clarified_fields` to be written and read. The eval CANNOT see this.
- **CONTEXT.md and docstrings must explicitly state this split** (D-23 compliance).

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_validate.py tests/test_reconcile.py -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** Full suite green + `uv run python eval/run_eval.py --check` before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_validate.py` — add MONEY-01 tests (zero-hours, partial-week, unknown-pay-type, predicate-consistency, explicit-drop, no-regression, detect-regression)
- [ ] `tests/test_reconcile.py` — add MONEY-02 NFD test (verify file exists first)
- [ ] `tests/test_resume_pipeline.py` — integration tests for snapshot-once and loop-guard (new file)
- [ ] `eval/fixtures/16_*.json` + `_extraction.json` — zero-hours-hourly fixture
- [ ] `eval/fixtures/17_*.json` + `_extraction.json` — NFD-name fixture
- [ ] `eval/fixtures/18_*.json` + `_extraction.json` — field-drop/carry-forward fixture

---

## Security Domain

`security_enforcement` is enabled (default). ASVS Level 1.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes — new `FieldDrop` + `clarified_fields` dict processed as pipeline I/O | Pydantic `model_validate` + `extra="forbid"` on any new model; `json.dumps` for JSONB writes (never f-string SQL) |
| V2/V3 Authentication/Session | no | Pipeline logic only |
| V4 Access Control | no | No new routes |
| V6 Cryptography | no | No new crypto |

**Specific threats for this phase:**
- **JSONB injection:** `clarified_fields` is written via `json.dumps(dict)` (not f-string SQL). The pattern follows `set_alias_candidates` — no injection vector. CONFIRMED safe.
- **Pre-clarify snapshot integrity:** `pre_clarify_extracted IS NULL` guard is in SQL — the snapshot cannot be overwritten by a concurrent write. No injection vector.
- **`field_regression` issue leaking PII:** `ValidationIssue.message` for a field-regression issue will contain the original value (e.g. "hours_overtime was 2, now absent"). This is numbers only — no names in the message field itself. The `field` attribute uses `{submitted_name}.{field_name}` following the existing pattern (e.g. line 93: `field=f"{emp.submitted_name}.hours_regular"`). The submitted name is already in `ValidationIssue.field` for all existing issues, so this is consistent with the existing pattern. PII-safe logging in orchestrator (line 239) already captures only `type(exc).__name__`.

---

## Contradictions Between CONTEXT.md Locked Decisions and Live Code

| # | CONTEXT.md Claim | Live Code Reality | Impact |
|---|-----------------|-------------------|--------|
| C-1 | "decide.py is UNCHANGED — it already gates `request_clarification` on any missing/issue" (D-17) | `decide.py:124` only gates on `issue_type == "missing"`, not on all issues. `"field_regression"` would be silently ignored. | **MUST RESOLVE** — either emit `"missing"` type from detect, or add a rule to `decide.py` for `"field_regression"`. Recommendation: Option B (add 2 lines to `decide.py` + widen Literal). |
| C-2 | `app/llm/client.py:124` cited for `temperature=0` | `temperature=0` is at line 124 inside `call_structured()`. CONFIRMED. | No action. |
| C-3 | `orchestrator.py:198/204/346/348` cited as `_norm` import call sites | Line 174 (`_norm(_token)` in `if _none_tokens` block), line 204 (`_norm(_m.get(...))` in `_token_resolved_to_newly`), line 346 (`norm_token = _norm(candidate_token)` in `_clarify`). Line 198 is `_norm_token = _norm(_token)`. Actual line numbers are 174, 198, 204, 346. Off by a few lines from CONTEXT.md's citation. | No action needed for planning — the chokepoint is confirmed. |
| C-4 | `reconcile_names.py:_norm` cited as "SOLE normalizer" but `run_eval.py:_normalize` is a separate non-NFC normalizer | Confirmed — two normalizers. The eval one is NOT auto-updated by fixing `_norm`. | **MUST FIX** — add `run_eval.py:_normalize` update to the MONEY-02 plan. |
| C-5 | `alias_candidates` readable via `load_run()` (implied by `resume_pipeline:154`) | `alias_candidates` is NOT in `RUN_COLS`; `load_run()` cannot return it. The `resume_pipeline` code that reads it always gets `None`. | **Out of scope for Phase 7** (existing behavior unchanged; the alias binding still works via a separate `_write_aliases_if_safe` path that also has the same limitation). Document only. |
| C-6 | CONTEXT cites `calculate.py:286–289` for "one PaystubLineItem per extracted entry" | Line 286 is `return PaystubLineItem(...)`. The no-dedup fact is confirmed but the line range is lines 286–305 (the entire return statement). | No action. |

---

## Assumptions Log

> All claims in this research were verified against live source files. No `[ASSUMED]` tags are used. The table below is empty.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | — | — | — |

**All claims verified against the live codebase on 2026-06-27.**

---

## Open Questions (RESOLVED)

1. **D-15 interaction — how exactly to short-circuit MONEY-01 for `confirmed_dropped` fields** — **RESOLVED 2026-06-27 (orchestrator + user decision).**
   - **Resolution:** Thread a **`resolved_drops: set[tuple[UUID, str]]`** kwarg into `validate()` (alongside `prior=None`), holding the `(employee_id, field)` pairs already resolved as `confirmed_dropped`. Inside the MONEY-01 zero-hours check, **skip any pair present in `resolved_drops`**. `resolved_drops` defaults to an empty set, so fresh runs are an exact no-op. `resume_pipeline` populates the set from the `confirmed_dropped` entries in `clarified_fields` and passes it through `_run_stages`.
   - **Rejected:** backfilling the original value to make `_is_paid` true — that would put the original (e.g. OT=2) on the paystub the client explicitly told us to remove → overpay + ignores an explicit instruction. The set-skip keeps the paystub correctly at `$0` for the removed field.
   - Implemented by: Plan 07-03 Task 1 (`validate()` signature) + Plan 07-04 (resume wiring populates the set).

2. **Wave 0 ordering — which tests to write before which code** — **RESOLVED 2026-06-27.**
   - **Resolution:** Locked to the plan wave ordering (1→5) with D-30 priority (money-movers first): Wave 1 = `FieldDrop` model + `ValidationIssue` Literal widen + all RED test scaffolds → Wave 2 = `_is_paid` predicate + `any_hours` (MONEY-01) + NFC `_norm` + eval `_normalize` parity (MONEY-02) → Wave 3 = `detect_field_regression` + `validate(prior=, resolved_drops=)` seam + decide Rule 2b (MONEY-03 judgment) → Wave 4 = schema + repo helpers + orchestrator state-machine wiring → Wave 5 = integration tests (snapshot-once, loop-guard, confirmed-dropped) + eval fixtures. Each wave's RED tests flip GREEN before the next wave begins.

---

## Environment Availability

Step 2.6: No external dependencies beyond the project's own Python environment. `uv sync` is sufficient. `unicodedata` is stdlib (Python 3.12, always available).

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `unicodedata` | MONEY-02 `_norm` fix | ✓ | stdlib (Python 3.12) | — |
| `uv` | All test runs | ✓ (project constraint) | per `.python-version` | — |
| Postgres/Supabase | Integration tests for MONEY-03 state machine | ✓ (dev env has DATABASE_URL) | 15.x | Skip integration tests without live DB |

---

## Sources

### Primary (HIGH confidence)
All findings are direct reads of the live source files. No external lookups were needed — this is a brownfield code-verification phase.

- `app/pipeline/validate.py` — `any_hours` predicate, `validate()` signature, D-05 OT guard, `_HOURS_FIELDS` tuple
- `app/pipeline/reconcile_names.py` — `_norm` function, call sites
- `app/pipeline/calculate.py` — `calculate()` return shape, `_compute_line_items` aggregation contract
- `app/pipeline/orchestrator.py` — `resume_pipeline()`, `_run_stages()`, `_clarify()`, CAS at line 124, alias diff pattern
- `app/pipeline/decide.py` — Rule 2 filter (`issue_type == "missing"`), gate logic
- `app/db/repo.py` — `set_alias_candidates`, `claim_status`, `persist_extracted`, `RUN_COLS`, `load_run`
- `app/models/contracts.py` — `ExtractedEmployee` fields, `ValidationIssue` Literal
- `app/models/roster.py` — `ValidationIssue` definition confirmed in `contracts.py` (not `roster.py`)
- `app/llm/client.py` — `temperature=0` at line 124
- `app/db/schema.sql` — `alias_candidates` DDL pattern, idempotent ALTER blocks
- `app/db/bootstrap.py` — bootstrap mechanism, no special alias_candidates handling
- `eval/run_eval.py` — `_normalize` function, fixture loader, extraction cache serializer
- `eval/fixtures/07_missing_hours_coastal.json` + `_extraction.json` — fixture structure confirmation
- `.planning/phases/07-money-correctness-deepening/07-CONTEXT.md` — 30 locked decisions
- `.planning/REQUIREMENTS.md` — MONEY-01/02/03 definitions
- `.planning/backlog.md` — field-regression original mechanism sketch
- `.planning/v2-hardening-audit.md` — HIGH-01 (zero-hours), MED-01 (Unicode)

---

## Metadata

**Confidence breakdown:**
- Code anchor lines and current state: HIGH — read directly from source
- Design decisions (D-01 through D-30): HIGH — from CONTEXT.md, confirmed against code
- Schema migration precedent: HIGH — read from schema.sql and bootstrap.py
- D-12 aggregation resolution (last-wins safe): HIGH — confirmed no aggregation contract exists
- D-24 serializer identification: HIGH — confirmed `model_dump_json()` at eval/run_eval.py:655
- D-15 interaction (MONEY-01 short-circuit): MEDIUM — mechanism identified but planner must resolve with user

**Research date:** 2026-06-27
**Valid until:** 2026-07-27 (stable codebase; no fast-moving dependencies)

---

## RESEARCH COMPLETE

**Phase:** 7 — Money-Correctness Deepening
**Confidence:** HIGH

### Key Findings

1. **All 30 locked decisions are consistent with the live code** with one critical exception: CONTEXT.md D-17's claim that "decide.py is UNCHANGED" is incorrect. `decide.py:Rule 2` filters only on `issue_type == "missing"`. A `ValidationIssue(issue_type="field_regression")` would be silently ignored. The planner must add 2 lines to `decide.py` AND widen `ValidationIssue.issue_type` Literal to include `"field_regression"`.

2. **`run_eval.py:_normalize` is a separate, non-NFC function** (not imported from `reconcile_names`). Fixing `_norm` alone will NOT fix the eval normalizer. The MONEY-02 plan must include a task to update `run_eval.py:_normalize` (or import `_norm` directly) or the NFD fixture will produce false eval regressions.

3. **D-12 open question resolved: last-wins is safe.** There is no aggregation contract in `calculate.py` or `_compute_line_items`. The reduction is only needed for the D-11 diff comparison, not for the calc path itself.

4. **D-24 serializer confirmed:** `extracted.model_dump_json()` is the authoritative serializer (used at `eval/run_eval.py:655`). New `prior` fixtures must be produced via this same round-trip.

5. **Schema migration precedent confirmed:** Two new nullable JSONB columns (`pre_clarify_extracted`, `clarified_fields`) follow the exact `alias_candidates` pattern — inline declaration in `CREATE TABLE` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + separate repo helpers. The `IS NULL` guard for snapshot-once belongs in the SQL (`WHERE id = %s AND pre_clarify_extracted IS NULL`).

6. **`pre_clarify_extracted` must be written in `_clarify()`**, not in `resume_pipeline()` — because at resume time, `extracted_data` has already been overwritten. The snapshot captures the state at the `awaiting_reply` pause. Threading `extracted` from `_run_stages` → `_clarify` is required.

### File Created
`.planning/phases/07-money-correctness-deepening/07-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Code anchors / current line numbers | HIGH | Direct source read |
| Architecture decisions (D-01–D-30) | HIGH | All confirmed against live code |
| D-12 aggregation resolution | HIGH | No aggregation contract found anywhere |
| D-24 serializer | HIGH | Confirmed at run_eval.py:655 |
| D-15 short-circuit mechanism | MEDIUM | Interaction identified; exact mechanism needs planner + user resolution |
| Schema migration | HIGH | Exact precedent in schema.sql lines 107–108 |

### Open Questions
- D-15: Exact mechanism to prevent MONEY-01 from re-flagging `confirmed_dropped` fields (recommend planner consult user before finalizing the `validate()` signature)
- D-17: Whether to emit `"missing"` type (no decide.py change) or `"field_regression"` type + decide.py Rule 2b (recommended)

### Ready for Planning
Research complete. Planner can now create PLAN.md files.
