# Phase 2: Walking Skeleton - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 22 new/modified files
**Analogs found:** 20 / 22 (2 have no role+data-flow analog — `client.py`, `main.py` webhook)

> The judgment spine is almost entirely *glue over the Phase 1 substrate*. The new
> surface adds NO contract types (all I/O shapes exist in `app/models/`), no new DB
> connection logic (`get_connection()`/`conn.transaction()` exist), and reuses the
> Phase 1 two-factor live-test guard verbatim. The one genuinely-new pattern with no
> analog is the OpenAI-compatible LLM client wrapper; the gate logic in `decide.py` is
> new *behavior* but reuses the existing `Decision`/`NameMatchResult` contracts.
>
> **All paths below are absolute-relative to the repo root** `/Users/pnhek/usf msds/github/payroll_agent`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/main.py` | route (webhook + approve/reject) | request-response | *(no FastAPI analog — Pattern 1 RESEARCH)* | no-analog (use RESEARCH §Pattern 1) |
| `app/pipeline/orchestrator.py` | service (state machine) | event-driven | `app/db/seed.py` (transaction + status-write loop) | role-match |
| `app/pipeline/extract.py` | service (pure stage) | transform | `app/db/seed.py` (Pydantic-validated construction) + `client.py` | partial (new LLM call; contract reuse) |
| `app/pipeline/reconcile_names.py` | service (pure stage) | transform | RESEARCH §Pattern 3 + `NameMatchResult` contract | partial (layer-1 pure code; layer-2 new) |
| `app/pipeline/validate.py` | service (pure stage) | transform | `app/models/roster.py` `_require_compensation_field` validator | role-match (pure issue emission) |
| `app/pipeline/decide.py` | service (the code gate) | transform | `app/models/contracts.py` `Decision` + RESEARCH §Pattern 4 | exact (contract exists; gate is new behavior) |
| `app/pipeline/calculate.py` | service (pure calc) | transform | `tests/test_seed_roundtrip.py::test_seed_high_earner_ss_cap_straddle` (FICA math) | partial (thin gross+FICA only) |
| `app/pipeline/compose_email.py` | service (drafting) | request-response | `client.py` (warm, no-JSON path) | partial |
| `app/llm/client.py` | service (vendor client) | request-response | *(no analog — RESEARCH §Pattern 2)* | no-analog (use RESEARCH §Pattern 2) |
| `app/llm/prompts/*.py` | config (prompt templates) | — | `app/config.py` (module-literal config) | partial |
| `app/email/gateway.py` | service (provider stub) | request-response | RESEARCH §Pattern 5 + `app/db/seed.py` (UUID literal + insert) | role-match |
| `app/db/repo.py` (run/threading persistence) | model (DB accessor) | CRUD | `app/db/seed.py` (parameterized upsert + `conn.transaction()`) | exact |
| `app/db/supabase.py` | — *(reused, unmodified)* | — | *(is itself the analog)* | n/a |
| `app/db/schema.sql` | migration (maybe + `reconciliation` col) | — | `app/db/schema.sql` (its own existing pattern) | exact |
| `app/config.py` | config | — | `app/config.py` (extend in place — live-LLM flag) | exact |
| `.env.example` | config | — | `.env.example` (append flag) | exact |
| `pyproject.toml` | config (register `live_llm` marker) | — | `pyproject.toml` (existing `integration` marker) | exact |
| `fixtures/*.json` | test fixture | — | `app/db/seed.py` (fixed-UUID literals) | role-match |
| `tests/test_gate.py` | test | — | `tests/test_models_contracts.py` (`Decision` construction asserts) | role-match |
| `tests/test_orchestrator_states.py` | test | — | `tests/test_seed_roundtrip.py` §1 (in-memory always-runs) | role-match |
| `tests/test_threading.py` / `test_webhook.py` | test | — | `tests/test_seed_roundtrip.py` §2 (live-DB two-factor guard) | role-match |
| `tests/test_live_llm.py` | test (live opt-in) | — | `tests/test_seed_roundtrip.py` §2 (`_SKIP_LIVE_DB` two-factor) | exact |
| `tests/test_status_drift.py` (modify IF new col) | test (drift guard) | — | `tests/test_status_drift.py` (its own pattern) | exact |

---

## Pattern Assignments

### `app/db/repo.py` — run/threading persistence (model, CRUD)

**Analog:** `app/db/seed.py` — this is the canonical write pattern: pooled `get_connection()` + explicit `conn.transaction()` + parameterized `conn.execute(...)`. Mirror it exactly; **never f-string SQL** (RESEARCH Security Domain: SQL-injection mitigation).

**Pooled-connection + transaction pattern** (`app/db/seed.py:264-269`):
```python
from app.db.supabase import get_connection

with get_connection() as conn:
    # All writes in a SINGLE explicit transaction (atomic; no orphaned rows)
    with conn.transaction():
        ...
```

**Parameterized upsert with `ON CONFLICT`** (`app/db/seed.py:281-297`) — copy the `%s` placeholder discipline and the `EXCLUDED.*` update form. The webhook's inbound dedupe is the analog of this conflict handling (RESEARCH §Pattern 1):
```python
conn.execute(
    """
    INSERT INTO businesses (id, name, contact_email, pay_period)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (id) DO UPDATE
      SET name = EXCLUDED.name, ...
          updated_at = now()
    """,
    (str(biz["id"]), biz["name"], biz["contact_email"], biz["pay_period"]),
)
```
For INGEST-01 inbound dedupe (RESEARCH §Pattern 1, G10), use `email_messages` `UNIQUE(message_id)` (`schema.sql:124`) with `ON CONFLICT (message_id) DO NOTHING` and check rowcount to decide whether to create a second run.

**JSONB persistence (Extracted/Decision → `payroll_runs`)** — RESEARCH §Code Examples lines 511-516; the `Decimal`-safe serialization is the Phase 1 D-06 default proven in `tests/test_models_contracts.py::test_decimal_json_serialization`:
```python
import json
conn.execute("UPDATE payroll_runs SET extracted_data=%s, updated_at=now() WHERE id=%s",
             (json.dumps(extracted.model_dump(mode="json")), str(run_id)))
conn.execute("UPDATE payroll_runs SET decision=%s, status=%s WHERE id=%s",
             (json.dumps(decision.model_dump(mode="json")), final_status, str(run_id)))
```
> `model_dump(mode="json")` renders `Decimal` → JSON string — the exact behavior locked by `tests/test_models_contracts.py:147-176`. Use it for `Decision`, `Extracted`, AND the per-name `list[NameMatchResult]` (D-A3-05).

**Read-back with explicit column list + `dict_row` (NO `SELECT *`)** — `tests/test_seed_roundtrip.py:362-372`. Critical because every contract is `extra="forbid"`; `SELECT *` pulls `created_at`/`updated_at` and raises `ValidationError`. Any place `repo.py` rebuilds a `Roster`/`Employee` from rows must use this:
```python
EMPLOYEE_COLS = ("id, business_id, full_name, known_aliases, pay_type, hourly_rate, "
                 "annual_salary, retirement_contribution_pct, filing_status, "
                 "step_2_checkbox, step_3_dependents, step_4a_other_income, "
                 "step_4b_deductions, ytd_ss_wages, pay_periods_per_year")
with get_connection() as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
    cur.execute(f"SELECT {EMPLOYEE_COLS} FROM employees WHERE business_id = %s", (str(biz_id),))
    rows = cur.fetchall()
roster = Roster(business_id=biz_id, employees=[Employee(**r) for r in rows])
```

**Threading header-chain lookup** (RESEARCH §Pattern 6, lines 414-421) — the `LIKE` on `references` MUST be parameterized (`%(references)s`), never interpolated (RESEARCH Security Domain). Match **only** `status='awaiting_reply'`; a header match to any other status is a late reply — log, do not resume (D-A4-02, Pattern 6 invariant 4).

---

### `app/pipeline/orchestrator.py` — the state machine (service, event-driven)

**Analog:** `app/db/seed.py` for the transaction-wrapped DB-write loop; **no Phase 1 analog for the try/except error-wrap** (it is new per D-A1-03 — RESEARCH §Pattern 4 / Architecture map).

**Status source of truth** — `app/models/status.py` `RunStatus` (11 values). The orchestrator drives transitions through `AWAITING_REPLY` and `AWAITING_APPROVAL`; persist every transition (RESEARCH diagram lines 217-219). Import and use the enum, never string literals:
```python
from app.models.status import RunStatus
# ... conn.execute("UPDATE payroll_runs SET status=%s ... ", (RunStatus.AWAITING_APPROVAL.value, ...))
```

**Error-wrap (new, D-A1-03):** wrap the whole run; any unhandled stage exception → persist `RunStatus.ERROR` + reason, never swallow silently. The closest Phase 1 *spirit* is `app/db/bootstrap.py`'s explicit `try/except` around `_safe_db_url` (`app/db/bootstrap.py:54-65`) — same "fail loudly, persist the safe artifact" intent.

**Branch SOLELY on `Decision.final_action`** (RESEARCH §Pattern 4 line 389, Anti-Pattern). Never read `model_action` in the orchestrator. `decide()` is called once, its `Decision` persisted, and the orchestrator switches on `final_action` only.

---

### `app/pipeline/decide.py` — THE CODE GATE (service, transform) — the thesis

**Analog:** `app/models/contracts.py` `Decision` (lines 94-113) is the exact output contract — already has `model_action`, `gate_triggered`, `gate_reasons`, `final_action`, `unresolved_names`, `missing_fields`, `confidence`, `reasons`. The gate *behavior* is new (RESEARCH §Pattern 4, lines 352-388; AI-SPEC §2).

**Output contract (already exists — do not redefine)** (`app/models/contracts.py:104-113`):
```python
class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_action: Literal["process", "request_clarification"]
    gate_triggered: bool
    gate_reasons: list[str]
    final_action: Literal["process", "request_clarification"]
    unresolved_names: list[str]
    missing_fields: list[str]
    confidence: Decimal = Field(ge=0, le=1)   # <0.8 fires the gate
    reasons: list[str]
```

**Gate rules (copy structure from RESEARCH §Pattern 4 lines 354-387):**
- **Per-name** confidence test — iterate `matches` and test EACH `m.confidence < Decimal("0.8")`. Do NOT gate on the collapsed scalar (D-A3-03a; RESEARCH Anti-Pattern line 428; the exact failure `test_per_name_not_average` guards).
- Confidence collapse = `min()` over all `NameMatchResult.confidence`, default `Decimal("1.0")` for a clean run (D-A3-03a, RESEARCH line 379).
- Unresolved: `m.match_type == "unknown"` or `m.matched_employee_id is None` (`NameMatchResult` Literal set is `app/models/roster.py:145`).
- Missing field: `[i.field for i in issues if i.issue_type == "missing"]` (`ValidationIssue.issue_type` Literal is `app/models/roster.py:165`).
- One-to-one (LLM-09, D-A3-02): pure code over `matched_employee_id` collisions.

**Decimal threshold discipline** — compare with `Decimal("0.8")`, never the float `0.8`, matching the all-Decimal contract convention (`contracts.py` D-05 header, every `confidence` field is `Decimal`). The `Decision` construction shape is already exercised in `tests/test_models_contracts.py:184-198` (`test_decision_gate_shape`) — your gate must produce exactly that shape.

---

### `app/pipeline/extract.py` / `reconcile_names.py` / `validate.py` (pure stages, transform)

**Analog (purity contract):** `app/models/roster.py` docstring (lines 1-11) is the binding constraint — *"Every judgment stage must be callable by the eval with only typed fixture inputs — zero DB access inside the function."* Signatures take `Roster`/`InboundEmail`/`Extracted` values, never `run_id`, never a connection (RESEARCH Anti-Pattern 2, line 425).

**`validate.py` analog** — the `@model_validator(mode="after")` issue-collection style in `app/models/roster.py:75-107` (`_require_compensation_field`): inspect fields, accumulate problems. `validate.py` emits `list[ValidationIssue]` instead of raising; map an absent required hours field (`None`, load-bearing per `contracts.py:58-64` and RESEARCH Pitfall 2) to `ValidationIssue(issue_type="missing")`.

**`reconcile_names.py` Layer 1 (deterministic, pure)** — RESEARCH §Pattern 3 lines 331-340; produces `NameMatchResult(match_type="exact"|"alias", confidence=Decimal("1.0"))`. Match against `Roster.employees[].full_name` and `.known_aliases` (the `known_aliases` fast path is seeded — `app/db/seed.py:83` Maria Chen, asserted in `tests/test_seed_roundtrip.py::test_seed_has_employee_with_known_aliases`). Layer 2 is the LLM call (uses `client.py` below); merge into one `list[NameMatchResult]`, one per submitted name.

**`extract.py`** — pure `(InboundEmail, Roster) -> Extracted` via `client.py` (below). Output is the `Extracted` contract (`contracts.py:78-87`); hours stay `Decimal | None` — never coerce absent hours to 0 (RESEARCH Pitfall 2; `contracts.py:58-64`).

---

### `app/llm/client.py` — the one OpenAI-compatible wrapper (service, request-response)

**Analog:** NONE in Phase 1 (no LLM call exists yet). Build from RESEARCH §Pattern 2 (lines 296-318). The **config** it consumes IS a Phase 1 analog:

**Per-tier config** — `app/config.py` `Settings` (lines 29-42) already carries `extraction_*` / `decision_*` / `draft_*` triples. Resolve a tier to `(base_url, model, api_key)` from `get_settings()` (`app/config.py:51-54`, `@lru_cache`):
```python
# app/config.py:30-42 — the per-tier surface the client routes over
extraction_model: str = "deepseek-v4-flash"
extraction_base_url: str = "https://api.deepseek.com"
extraction_api_key: str = ""
decision_model: str = "moonshot-v1-8k"          # reconcile + decide tiers
draft_model: str = "moonshot-v1-8k"             # compose_email
```

**Call shape (RESEARCH §Pattern 2 lines 297-318):** `OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)`; `temperature=0`; `response_format={"type": "json_object"}`; DeepSeek non-thinking toggle via `extra_body={"thinking": {"type": "disabled"}}` (⚠️ exact param unconfirmed — STATE.md blocker); validate with `response_model.model_validate_json(content)`; ONE reflective retry on `ValidationError`/empty content, then raise. Every structured prompt MUST carry the literal word "json" + an example shape (RESEARCH Pitfall 1). Do NOT use `.parse()` (CLAUDE.md — DeepSeek lacks strict `json_schema`).

---

### `app/email/gateway.py` — stub email gateway (service, request-response)

**Analog:** RESEARCH §Pattern 5 (lines 396-402) for the interface; `app/db/seed.py` for the synthetic-UUID-literal + parameterized insert style. Two functions only: `parse_inbound(raw) -> InboundEmail`, `send_outbound(...) -> message_id`.

**Synthetic Message-ID + outbound row** (RESEARCH §Pattern 5):
```python
import uuid
message_id = f"<{uuid.uuid4()}@payroll-agent.local>"   # RFC-shaped, collision-free
# then insert an email_messages(direction='outbound', message_id=...) row via repo.py
```
The `email_messages` insert mirrors the `seed.py` parameterized-insert discipline (`app/db/seed.py:309-358`). Returned `message_id` is stored on the run for the reply chain (D-A4-02).

---

### `app/db/schema.sql` — schema change IF D-A3-05 chooses a new column

**Analog:** `app/db/schema.sql` itself. The `payroll_runs.extracted_data` and `payroll_runs.decision` JSONB columns ALREADY exist (`schema.sql:79-80`) — no add needed for those. If the planner chooses option (a) for D-A3-05, add `reconciliation JSONB` to `payroll_runs` following the exact inline-comment + `JSONB` style of lines 79-80:
```sql
extracted_data  JSONB,      -- D-06: persisted from Extracted.model_dump(mode="json")
decision        JSONB,      -- D-06: persisted from Decision.model_dump(mode="json")
reconciliation  JSONB,      -- D-A3-05: list[NameMatchResult].model_dump(mode="json") per run
```
A new JSONB column is safe for the drift guard (it checks only `status`/enum CHECK value sets, not column lists — see `tests/test_status_drift.py:81-86`). The schema is applied idempotently by `app/db/bootstrap.py:88-102` (`CREATE TABLE IF NOT EXISTS`); a new column on an existing table needs an `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` block mirroring the deferred-FK `DO $$ ... $$` idempotency pattern (`schema.sql:143-155`) OR a destructive `--reset` bootstrap.

---

### `app/config.py` + `.env.example` + `pyproject.toml` — config (extend in place)

**`app/config.py`** (extend the existing `Settings`, lines 16-48): add the live-LLM opt-in flag (name is Claude's discretion — mirror `ALLOW_DB_RESET`). The class already uses `SettingsConfigDict(env_file=".env", extra="ignore")` (line 48), so a new bool field with a default just works.

**`.env.example`** — append the new flag below `TAX_YEAR=2026` (line 11), mirroring the existing flat `KEY=value` style.

**`pyproject.toml`** — register the `live_llm` marker alongside the existing `integration` marker (lines 12-16). Copy the exact form:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests as requiring a live database (deselect with -m 'not integration')",
    "live_llm: marks tests as hitting real DeepSeek/Kimi APIs (deselect with -m 'not live_llm')",
]
```

---

### `fixtures/*.json` — committed demo fixtures (test fixture)

**Analog:** `app/db/seed.py` fixed-UUID-literal discipline (lines 47-69, "All UUIDs are fixed/stable literals so FK references in later fixture files remain stable across runs (D-11)"). Fixtures are canonical `InboundEmail` JSON (shape = `contracts.py:30-47`). The hero fixture submits **`David Reyez`** against the seeded **David Reyes** (`app/db/seed.py:117-138`, emp 3, `e0000003-...`). The reply fixture's `in_reply_to` points at the clarification's synthetic Message-ID (D-A4-02).

---

### Test files (test)

**`tests/test_live_llm.py` — EXACT analog `tests/test_seed_roundtrip.py` §2** (lines 26-27, 271-277). Reuse the two-factor guard verbatim, swapping the env-var pair (RESEARCH §Code Examples lines 524-545):
```python
# tests/test_seed_roundtrip.py:26-27 — the two-factor pattern to mirror
_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"
# tests/test_seed_roundtrip.py:271-277 — the skip mark to mirror
_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)
```
Live-LLM version: `_HAS_LLM_KEYS = bool(EXTRACTION_API_KEY and DECISION_API_KEY)`; `_LIVE_LLM = os.environ.get("ALLOW_LIVE_LLM") == "1"`; mark `@pytest.mark.live_llm`. The hero live test asserts `model_action == "process"` AND `final_action == "request_clarification"` AND a per-name confidence `< 0.8` (D-A4-01a).

**`tests/test_gate.py` — analog `tests/test_models_contracts.py`** (the `Decision`-construction asserts, lines 184-198). Feed `decide()` a hand-authored `list[NameMatchResult]` with `confidence=Decimal("0.6")` + `model_action="process"`, assert `final_action == "request_clarification"`. This is mock-driven, deterministic, DB-free — the always-runs class.

**`tests/test_orchestrator_states.py` / `test_webhook.py` — split analog** `tests/test_seed_roundtrip.py` (§1 always-runs in-memory vs §2 live-DB two-factor). The in-memory state-machine assertions (gate fires, both pauses reached) run always with a mocked LLM; the persistence round-trip (LLM-08, `test_decision_roundtrip`) goes behind `@pytest.mark.integration` + the `_SKIP_LIVE_DB` guard, exactly like `tests/test_seed_roundtrip.py:300-457`. The webhook test relies on `TestClient` running `BackgroundTasks` synchronously (RESEARCH §Pattern 1, line 286) — no `@pytest.mark.integration` needed unless it touches the DB.

**`tests/test_status_drift.py` — modify ONLY IF a new status value or CHECK-enumerated column is added.** A new JSONB `reconciliation` column needs NO change (drift guard only parses `CHECK (col IN (...))` value sets — `tests/test_status_drift.py:34-65, 81-86`). If a NEW `RunStatus` enum value is introduced, add it to BOTH `app/models/status.py` AND the `payroll_runs.status` CHECK (`schema.sql:66-78`), and update the count assertion `test_status_exact_count_is_eleven` (`tests/test_status_drift.py:118-131`). Phase 2 is NOT expected to need a new status (the 11 cover both pauses).

---

## Shared Patterns

### DB access (pooled connection + transaction)
**Source:** `app/db/supabase.py` `get_connection()` (lines 51-63) + `app/db/seed.py:264-269` (`conn.transaction()`).
**Apply to:** `orchestrator.py`, `repo.py`, `email/gateway.py` — every file that touches Postgres.
```python
from app.db.supabase import get_connection
with get_connection() as conn:
    with conn.transaction():
        conn.execute("...", (param1, param2))   # %s placeholders ONLY — never f-string SQL
```

### Decimal/JSONB serialization
**Source:** `app/models/contracts.py` D-06 header (lines 4-9) + `tests/test_models_contracts.py::test_decimal_json_serialization` (lines 147-176).
**Apply to:** `repo.py` persistence of `Extracted`, `Decision`, `list[NameMatchResult]`.
```python
json.dumps(obj.model_dump(mode="json"))   # Decimal -> JSON string, lossless at the jsonb boundary
```

### Pydantic-validated construction before any side effect
**Source:** `app/db/seed.py:71-74` (Employees constructed at import time; `ValidationError` surfaces before any DB write).
**Apply to:** every stage output (`Extracted`, `Decision`, `NameMatchResult`) — validate via `model_validate_json` / direct construction so a bad LLM payload fails at the contract boundary, triggering the reflective retry.

### Two-factor env-gated live tests
**Source:** `tests/test_seed_roundtrip.py:26-27, 271-277`.
**Apply to:** `test_live_llm.py` (live model) AND any new live-DB integration test. Default CI runs `pytest -m "not integration and not live_llm"` — green and free.

### Parameterized SQL only (injection defense)
**Source:** `app/db/seed.py` (every `conn.execute` uses `%s`); RESEARCH Security Domain V5/Tampering.
**Apply to:** all of `repo.py` — especially the threading `references LIKE %(references)s` query (RESEARCH §Pattern 6 line 419); never interpolate a Message-ID into SQL.

### `extra="forbid"` read-back discipline
**Source:** `tests/test_seed_roundtrip.py:351-379` (explicit column list + `dict_row`, no `SELECT *`).
**Apply to:** any `repo.py` function rebuilding a contract object from DB rows (e.g. loading the `Roster` for a run) — `SELECT *` would pass `created_at`/`updated_at` and crash `extra="forbid"`.

---

## No Analog Found

Files with no close Phase 1 match (planner uses RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason / Where to look |
|------|------|-----------|------------------------|
| `app/main.py` (webhook + approve/reject) | route | request-response | No FastAPI surface exists in Phase 1. Use RESEARCH §Pattern 1 (lines 271-286, `BackgroundTasks` + fast 200 + `TestClient`-synchronous testability). |
| `app/llm/client.py` | service | request-response | No LLM call exists in Phase 1. Use RESEARCH §Pattern 2 (lines 296-323) for the `OpenAI(base_url=...)` + JSON-mode + reflective-retry + DeepSeek non-thinking toggle. Config it reads (`Settings` tiers) IS a Phase 1 analog (`app/config.py:29-42`). |

> Both no-analog files are *vendor-surface* code (HTTP framework, LLM SDK) — the
> RESEARCH patterns are concrete and cited to official docs. Everything that touches
> *project state or contracts* has a real Phase 1 analog above.

## Metadata

**Analog search scope:** `app/` (config, db, models), `tests/`, repo-root config (`pyproject.toml`, `.env.example`, `requirements.txt`).
**Files scanned:** 13 Phase 1 source/test/config files (all read in full — every file ≤ 540 lines, one pass each).
**Pattern extraction date:** 2026-06-21
