# Phase 4: The Eval (the proof) - Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 7 new/modified files
**Analogs found:** 7 / 7

---

## File Classification

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------------|------|-----------|----------------|---------------|
| `eval/fixtures/*.json` (×15) | fixture | batch | `fixtures/clean_happy_path.json` | exact — same InboundEmail JSON shape; new `expected` block is additive |
| `eval/fixtures/*_extraction.json` (×15) | fixture | batch | `fixtures/clean_happy_path.json` (schema) + `app/models/contracts.py` Extracted model | role-match — record-once cached extraction beside each fixture |
| `eval/run_eval.py` | utility / scorer | batch + transform | `tests/test_demo_fixtures.py` (fixture-load/replay) + `app/pipeline/orchestrator.py` `_run_stages` (stage call order) | role-match — scores the same pipeline stages the orchestrator calls |
| `eval/run_eval.py` (chart/SVG section) | utility | transform | `tests/test_federal_withholding.py` (parametrize + assertion pattern) | partial — same table-driven score aggregation philosophy |
| `.github/workflows/eval.yml` | config / CI | batch | none — project's FIRST workflow | no analog |
| `eval/draft_candidate_emails.py` | utility | request-response | `app/llm/client.py` `call_text` | role-match — uses the same `call_text` / Kimi draft tier |
| `pyproject.toml` (uv add --dev matplotlib) | config | n/a | `pyproject.toml` existing dev group | exact — same `uv add --dev` pattern |

---

## Pattern Assignments

### `eval/fixtures/*.json` — labeled eval fixtures (one file per fixture)

**Analog:** `fixtures/clean_happy_path.json`

**Input envelope shape** (`fixtures/clean_happy_path.json` lines 1-11):
```json
{
  "id": "a0000001-0000-0000-0000-000000000001",
  "message_id": "<clean-happy-001@coastalcleaning.example>",
  "in_reply_to": null,
  "references_header": null,
  "subject": "Payroll hours for week of 2026-06-15",
  "from_addr": "payroll@coastalcleaning.example",
  "to_addr": "agent@payroll-agent.local",
  "body_text": "...",
  "created_at": "2026-06-15T09:30:00Z"
}
```

**Key facts the new eval fixtures must satisfy (drawn from `tests/test_demo_fixtures.py` lines 61-69):**
- `from_addr` MUST match a seeded `businesses.contact_email` — validated via `seed(dry_run=True).businesses`
- `InboundEmail.model_validate(payload)` must succeed (Pydantic v2 strict validation, `extra="forbid"` from `app/models/contracts.py:42`)
- Three seeded `contact_email` values available: `payroll@coastalcleaning.example` (Business 1, weekly), `hr@metrodeli.example` (Business 2, weekly), `finance@summittech.example` (Business 3, biweekly)

**`expected` block additions** — extend each fixture file with an `expected` top-level key alongside the input fields (D-02/D-03). The schema must carry:

```json
{
  "id": "...",
  "message_id": "...",
  "from_addr": "hr@metrodeli.example",
  "body_text": "...",
  "created_at": "...",

  "fixture_category": "collision",

  "expected": {
    "extracted": {
      "employees": [
        {
          "submitted_name": "D. Reyes",
          "hours_regular": "40",
          "hours_overtime": null,
          "hours_vacation": null,
          "hours_sick": null,
          "hours_holiday": null,
          "contribution_401k_override": null
        }
      ],
      "pay_period_start": "2026-06-15",
      "pay_period_end": null
    },
    "reconciliation": [
      {
        "submitted_name": "D. Reyes",
        "name_category": "collision",
        "expected_source": "none",
        "expected_resolved": false,
        "expected_matched_employee_id": null
      }
    ],
    "decision": {
      "final_action": "request_clarification",
      "gate_reasons_contains": ["D. Reyes"],
      "unresolved_names": ["D. Reyes"],
      "missing_fields": []
    }
  }
}
```

Notes on field types:
- Hours fields are **JSON strings** (Decimal serializes to string via `model_dump(mode="json")` — `app/models/contracts.py` lines 24-27, D-06)
- `fixture_category` uses the taxonomy enum from D-03: `exact | stored-alias | first-time-alias | typo | collision | unknown | missing-hours | vague-hours | buried-reply`
- `name_category` on each reconciliation entry drives the **per-NAME** reconciliation chart (separate from `fixture_category`, D-03)
- `net_pay` is deliberately NOT labeled (D-02 — Phase 3 goldens own calc correctness)

---

### `eval/fixtures/*_extraction.json` — committed cached extraction (one per fixture)

**Pattern source:** `app/models/contracts.py:103-112` (`Extracted` model) + `app/models/contracts.py:83-100` (`ExtractionPayload`)

**Shape** — the cached file holds the raw `Extracted` JSON that `extract()` would return, serialized via `model_dump(mode="json")`:

```json
{
  "run_id": "00000000-0000-0000-0000-000000000000",
  "employees": [
    {
      "submitted_name": "D. Reyes",
      "hours_regular": "40",
      "hours_overtime": null,
      "hours_vacation": null,
      "hours_sick": null,
      "hours_holiday": null,
      "contribution_401k_override": null
    }
  ],
  "pay_period_start": "2026-06-15",
  "pay_period_end": null
}
```

Notes:
- `run_id` in the cache can be a zero-UUID placeholder — the eval replays from cache and stamps the eval's own run identity
- `hours_*` values are JSON strings (Decimal → string), not numbers — must parse with `Decimal(v)` when comparing, NOT float
- **Never load cached extraction with `json.loads` into raw dicts** — always round-trip through `Extracted.model_validate(data)` to enforce `extra="forbid"` and catch schema drift

---

### `eval/run_eval.py` — scorer, chart emitter, `--check` gate

**Primary analogs:**
- `tests/test_demo_fixtures.py` — fixture-load-from-JSON + stage-replay pattern
- `app/pipeline/orchestrator.py:168` `_run_stages` — exact stage call order
- `tests/test_federal_withholding.py` — parametric scoring discipline (Decimal exact equality, `ROUND_HALF_UP`)
- `app/config.py:50` — `allow_live_llm` two-factor gate pattern

**Fixture-load pattern** (`tests/test_demo_fixtures.py` lines 26-34, 63-69):
```python
import json
import pathlib
from app.models.contracts import InboundEmail
from app.db.seed import seed

_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clean_happy_path.json"

# Load + validate:
payload = json.loads(_FIXTURE.read_text())
email = InboundEmail.model_validate(payload)

# Roster from seed — no live DB:
seeded = seed(dry_run=True)
seeded_emails = {b["contact_email"] for b in seeded.businesses}
assert email.from_addr in seeded_emails
```

**Roster-from-seed pattern** (`tests/conftest.py` lines 152-160):
```python
from app.db.seed import seed
from app.models.roster import Roster

seeded = seed(dry_run=True)
business_id = next(
    b["id"] for b in seeded.businesses
    if b["contact_email"] == fixture_from_addr
)
employees = [e for e in seeded.employees if e.business_id == business_id]
roster = Roster(business_id=business_id, employees=employees)
```

**Stage call order** (`app/pipeline/orchestrator.py:168-183`) — the eval MUST mirror this exact order:
```python
from app.pipeline.extract import extract
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.validate import validate
from app.pipeline.decide import decide

# Path (a) — isolated: feed labeled expected extraction
extracted = Extracted.model_validate(cached_json)   # replay from cache
submitted_names = [e.submitted_name for e in extracted.employees]
matches = reconcile_names(submitted_names, roster)   # pure
issues = validate(extracted, roster, matches)         # pure
decision = decide(extracted, matches, issues)         # pure, no LLM
```

**`allow_live_llm` two-factor gate** (`app/config.py:46-52`) — the `--record` step and the optional judge reuse this exactly:
```python
from app.config import get_settings

settings = get_settings()
if not settings.allow_live_llm:
    raise SystemExit(
        "Live LLM calls require ALLOW_LIVE_LLM=true in the environment. "
        "Set it explicitly to re-record extraction cache."
    )
# Also check that the relevant API key is non-empty:
if not settings.extraction_api_key:
    raise SystemExit("EXTRACTION_API_KEY must be set for --record mode.")
```

**Decimal exact equality for hours/money** (`tests/test_calculate.py` lines 29-36, `tests/test_federal_withholding.py` lines 396-399):
```python
from decimal import Decimal, ROUND_HALF_UP

# Hours comparison — exact Decimal equality, no float tolerance (D-06):
assert Decimal(actual_hours) == Decimal(expected_hours), (
    f"hours_regular: expected {expected_hours}, got {actual_hours}"
)

# Money whole-dollar comparison (for chart/summary only):
engine_whole_dollar = result.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
```

**`seed(dry_run=True)` import pattern** (`tests/test_calculate.py` lines 18-24, `tests/test_federal_withholding.py` lines 140-148):
```python
from app.db.seed import seed

@pytest.fixture()
def thomas_bergmann():
    seeded = seed(dry_run=True)
    return next(
        e for e in seeded.employees
        if e.full_name == "Thomas Bergmann"
    )
```

For `run_eval.py` (non-pytest), use the same `seed(dry_run=True)` call directly — no fixture wrapping needed.

**Extraction precision/recall scoring pattern** (D-06) — employees aligned by normalized `submitted_name`:
```python
import unicodedata

def _normalize(name: str) -> str:
    """casefold + collapse whitespace — same normalization reconcile_names uses."""
    return " ".join(name.casefold().split())

# Align actual vs expected employees by normalized submitted_name:
actual_by_name = {_normalize(e.submitted_name): e for e in actual_extracted.employees}
expected_by_name = {_normalize(e["submitted_name"]): e for e in expected["extracted"]["employees"]}

matched = set(actual_by_name) & set(expected_by_name)
false_positives = set(actual_by_name) - set(expected_by_name)   # precision miss
false_negatives = set(expected_by_name) - set(actual_by_name)   # recall miss

precision = len(matched) / (len(matched) + len(false_positives)) if actual_by_name else 1.0
recall    = len(matched) / (len(matched) + len(false_negatives)) if expected_by_name else 1.0
f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
```

**Decision two-level scoring pattern** (D-10):
```python
# Level 1 — final_action match (headline):
action_correct = (decision.final_action == expected_decision["final_action"])

# Level 2 — gate-structure set-match (rigor layer):
gate_reasons_match = (
    set(decision.gate_reasons) == set(expected_decision["gate_reasons"])
    or all(s in " ".join(decision.gate_reasons) for s in expected_decision.get("gate_reasons_contains", []))
)
unresolved_match = set(decision.unresolved_names) == set(expected_decision["unresolved_names"])
missing_match    = set(decision.missing_fields)   == set(expected_decision["missing_fields"])
gate_struct_ok   = gate_reasons_match and unresolved_match and missing_match
```

**D-09 wiring smoke test** — assert `calculate()` equals the Phase-3 golden for Thomas Bergmann. This test can live in `run_eval.py` as a standalone function called before the main scoring loop, OR as a pytest in `tests/`. The golden values come from `tests/test_federal_withholding.py:1097-1137`:

```python
from decimal import Decimal
from app.db.seed import seed
from app.pipeline.calculate import calculate

def assert_wiring_smoke_test():
    """D-09: decide→calculate wiring smoke. Asserts == Phase-3 golden (test_federal_withholding.py:1097)."""
    seeded = seed(dry_run=True)
    thomas = next(e for e in seeded.employees if e.full_name == "Thomas Bergmann")
    zero_hours = {k: Decimal("0") for k in
                  ("hours_regular", "hours_overtime", "hours_vacation", "hours_sick", "hours_holiday")}
    item = calculate(zero_hours, thomas)
    # Phase-3 golden values (test_federal_withholding.py lines 1131-1137, verified penny-exact):
    assert item.gross_pay          == Decimal("9230.77"), f"gross {item.gross_pay}"
    assert item.pretax_401k        == Decimal("738.46"),  f"401k {item.pretax_401k}"
    assert item.federal_withholding == Decimal("881.39"),  f"fed_wh {item.federal_withholding}"
    assert item.fica_ss             == Decimal("37.20"),   f"fica_ss {item.fica_ss}"
```

**`summary.json` + SVG output pattern** — no direct analog; structure is the planner's call. The machine-readable contract the Phase 5 dashboard (DASH-04) consumes must include:
- `suite_run_id` (UUID, generated per run)
- `extraction_model_id` (string, from `settings.extraction_model` — records which model produced the cache, per D-05)
- `per_category` metrics (extraction F1 / reconciliation accuracy-on-category / decision fraction)
- `confusion_matrix` (process×clarify, with `false_process_count` as the headline)
- `per_fixture` details (one entry per fixture: fixture_id, category, stage outputs, scores)
- `generated_at` (ISO timestamp)

**`--check` mode pattern** (D-17) — compare parsed+rounded values, NOT file bytes:
```python
import json
import argparse
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Regression gate: score against committed cache, compare to summary.json")
    parser.add_argument("--record", action="store_true",
                        help="Re-record extraction cache (requires ALLOW_LIVE_LLM=true)")
    args = parser.parse_args()

    if args.record:
        _require_live_llm()   # gates on allow_live_llm + api key

    results = _score_all_fixtures()  # always runs scoring

    if args.check:
        committed = json.loads(pathlib.Path("eval/summary.json").read_text())
        _assert_regression(results, committed)  # compare parsed floats, not bytes
        print("--check passed: no regression against committed summary.json")
        sys.exit(0)

    _write_summary_json(results)
    _write_svg_chart(results)

if __name__ == "__main__":
    main()
```

---

### `.github/workflows/eval.yml` — project's first CI workflow

**No analog** — this is the first `.github/workflows/` file in the project. Patterns come from CONTEXT.md D-17 and standard GitHub Actions conventions.

**Structure to implement:**

```yaml
name: eval

on:
  push:
    branches: ["master"]
  workflow_dispatch:
    inputs:
      live_record:
        description: "Re-record extraction cache (requires secrets)"
        type: boolean
        default: false

jobs:
  check:
    # Push job: hermetic regression gate — no live LLM, no DB
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv sync
      - run: uv run python eval/run_eval.py --check
    # NOTE: ALLOW_LIVE_LLM is intentionally NOT set → gate stays hermetic

  record:
    # workflow_dispatch only: live re-record (requires API keys in secrets)
    if: github.event_name == 'workflow_dispatch' && inputs.live_record
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - run: uv sync
      - run: uv run python eval/run_eval.py --record
        env:
          ALLOW_LIVE_LLM: "true"
          EXTRACTION_API_KEY: ${{ secrets.EXTRACTION_API_KEY }}
          DATABASE_URL: "placeholder"   # not needed for record-only
```

**Key constraints (from CLAUDE.md tooling rule + D-17):**
- `uv sync` not `pip install` — no `requirements.txt`
- `uv run python eval/run_eval.py` not `python eval/run_eval.py`
- `DATABASE_URL` env var has no default in `app/config.py:27` (fails fast at import); the check job MUST provide a placeholder value or use `PYTHONPATH` isolation if `run_eval.py` avoids importing `app.config` at module level
- `astral-sh/setup-uv@v5` is the current uv GitHub Action (matches the uv tooling rule)

---

### `eval/draft_candidate_emails.py` — bootstrap drafting helper (~20 lines)

**Analog:** `app/llm/client.py:155-183` `call_text`

**Core pattern** (`app/llm/client.py` lines 155-182):
```python
from app.llm.client import call_text

# Draft tier = Kimi (moonshot-v1-*) — NOT DeepSeek (anti-leakage rule D-19)
draft = call_text(
    tier="draft",
    messages=[
        {
            "role": "user",
            "content": (
                "Draft a realistic but intentionally messy payroll email "
                "for a small business. Include at least one name abbreviation "
                "or nickname that might not exactly match a full employee name. "
                "Be casual and informal. Include a signature."
            ),
        }
    ],
    temperature=0.9,   # warmer than extraction — variety is the goal
)
if draft is None:
    print("No content returned — retry or hand-write the fixture.")
else:
    print(draft)
```

**Anti-leakage pattern** (D-19) — the helper MUST use `tier="draft"` (Kimi), not `tier="extraction"` (DeepSeek). The `call_text` function routes by tier via `_resolve_tier` from `app/config.py` settings. No direct model name in the script — keep it config-driven.

**`allow_live_llm` gate** (same two-factor pattern as `--record`):
```python
from app.config import get_settings
settings = get_settings()
if not settings.allow_live_llm:
    raise SystemExit("Set ALLOW_LIVE_LLM=true to use this helper.")
if not settings.draft_api_key:
    raise SystemExit("DRAFT_API_KEY must be set.")
```

---

## Shared Patterns

### Decimal-everywhere (D-05/D-06)

**Source:** `app/models/contracts.py:24-27`, `app/models/roster.py:43-68`, `tests/test_calculate.py:29-36`

**Apply to:** All scoring code in `run_eval.py`, fixture schema parsing, the D-09 wiring smoke test.

```python
from decimal import Decimal, ROUND_HALF_UP

# NEVER use float for hours or money — always Decimal:
hours = Decimal(raw_string_value)   # from JSON "40" -> Decimal("40")
money = Decimal(raw_string_value)   # from JSON "9230.77" -> Decimal("9230.77")

# Equality for hours is EXACT (discrete, no tolerance):
assert hours_actual == hours_expected

# Money rounding follows the project pin:
rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

### `seed(dry_run=True)` — no-DB roster loading

**Source:** `app/db/seed.py:275-298`, used in `tests/test_demo_fixtures.py:65-69`, `tests/test_calculate.py:18-22`, `tests/test_federal_withholding.py:140-148`

**Apply to:** `run_eval.py` (fixture→roster binding, D-04), `eval/draft_candidate_emails.py` (if it validates from_addr).

```python
from app.db.seed import seed

seeded = seed(dry_run=True)

# Build roster for a specific business by contact_email:
biz = next(b for b in seeded.businesses if b["contact_email"] == fixture_from_addr)
roster = Roster(
    business_id=biz["id"],
    employees=[e for e in seeded.employees if e.business_id == biz["id"]],
)

# Seed values for reference:
# Business 1 — payroll@coastalcleaning.example — weekly (52), employees: Maria Chen, James Okafor
# Business 2 — hr@metrodeli.example           — weekly (52), employees: David Reyes (e3), Priya Nair (e4), Daniel Reyes (e7)
# Business 3 — finance@summittech.example     — biweekly (26), employees: Thomas Bergmann (e5), Sandra Kim (e6)
#
# Collision pair (D-21-02): David Reyes (e3) + Daniel Reyes (e7) share alias "D. Reyes"
# SS-straddle (D-13): Thomas Bergmann, ytd_ss_wages=Decimal("183900.00"),
#                     per_period_gross=$9,230.77, remaining_cap=$600, fica_ss=$37.20
```

### `allow_live_llm` two-factor gate

**Source:** `app/config.py:46-52`

**Apply to:** `run_eval.py --record` mode, `eval/draft_candidate_emails.py`.

```python
from app.config import get_settings

def _require_live_llm(*, tier: str = "extraction") -> None:
    settings = get_settings()
    if not settings.allow_live_llm:
        raise SystemExit(
            "Re-record requires ALLOW_LIVE_LLM=true. "
            "This is intentionally non-default to keep CI hermetic."
        )
    key = settings.extraction_api_key if tier == "extraction" else settings.draft_api_key
    if not key:
        raise SystemExit(f"{tier.upper()}_API_KEY must be set for live calls.")
```

### `InboundEmail.model_validate` fixture loading

**Source:** `tests/test_demo_fixtures.py:61-69`, `tests/conftest.py:132-144`

**Apply to:** `run_eval.py` fixture loading loop, fixture validation in `draft_candidate_emails.py`.

```python
import json
import pathlib
from app.models.contracts import InboundEmail

def load_fixture(path: pathlib.Path) -> dict:
    """Load one eval fixture file, validate the input portion."""
    raw = json.loads(path.read_text())
    # Validate the InboundEmail input fields (strip 'expected' + 'fixture_category' before validate):
    input_fields = {k: v for k, v in raw.items() if k not in ("expected", "fixture_category")}
    InboundEmail.model_validate(input_fields)  # raises on schema violation
    return raw
```

### Pydantic `model_dump(mode="json")` serialization

**Source:** `tests/conftest.py:281-289`, `app/models/contracts.py:24-27` (D-06)

**Apply to:** Writing cached extraction JSON beside each fixture (the `--record` path in `run_eval.py`).

```python
# Write cached extraction:
cached_path = fixture_path.parent / (fixture_path.stem + "_extraction.json")
cached_path.write_text(
    json.dumps(extracted.model_dump(mode="json"), indent=2)
)

# Read cached extraction back:
cached_data = json.loads(cached_path.read_text())
extracted = Extracted.model_validate(cached_data)
```

---

## Phase-3 Golden Values (for D-09 wiring smoke test)

These values come from `tests/test_federal_withholding.py:1097-1137` (Thomas Bergmann over-ceiling fixture, verified penny-exact against paycheckcity.com):

| Field | Golden Value | Source |
|-------|-------------|--------|
| `gross_pay` | `Decimal("9230.77")` | `test_federal_withholding.py:1131` |
| `pretax_401k` | `Decimal("738.46")` | `test_federal_withholding.py:1132` |
| `federal_withholding` | `Decimal("881.39")` | `test_federal_withholding.py:1134` |
| `fica_ss` | `Decimal("37.20")` | `tests/test_federal_withholding.py:1069` (CALC-04) |

Employee: Thomas Bergmann — `seed(dry_run=True)`, `e.full_name == "Thomas Bergmann"`.
Hours input: all five fields = `Decimal("0")` (salaried — zero hours still yields `annual/26` gross).

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.github/workflows/eval.yml` | config / CI | batch | No `.github/workflows/` directory exists yet — project's first CI workflow (STATE.md note confirmed). Standard GitHub Actions structure applies. |

---

## Metadata

**Analog search scope:** `app/`, `tests/`, `fixtures/`
**Files scanned:** 12 source files read in full
**Key seeded data confirmed:**
- Collision pair: David Reyes (`e0000003`, Business 2) + Daniel Reyes (`e0000007`, Business 2) share `known_aliases=["D. Reyes"]` — `app/db/seed.py:134-150` and `245-261`
- SS-straddle: Thomas Bergmann (`e0000005`, Business 3), `ytd_ss_wages=Decimal("183900.00")`, `pay_periods_per_year=26`, `annual_salary=Decimal("240000.00")`, `retirement_contribution_pct=Decimal("0.08")` — `app/db/seed.py:192-209`
- Three business contact emails: `payroll@coastalcleaning.example`, `hr@metrodeli.example`, `finance@summittech.example` — `app/db/seed.py:53-69`
- `allow_live_llm: bool = False` default — `app/config.py:50`
- Two model tiers: `extraction` = DeepSeek, `draft` = Kimi — `app/config.py:30-40`, `app/llm/client.py:40`
**Pattern extraction date:** 2026-06-22
