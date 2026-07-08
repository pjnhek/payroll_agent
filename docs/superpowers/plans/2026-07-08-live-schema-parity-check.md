# Live Schema-Parity Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect and prevent live-DB schema drift — the class of bug where deployed code SELECTs a column the live Supabase DB never got migrated (Phase 11's `clarification_round` crash).

**Architecture:** Three independent layers. (1) A pure-logic module `app/db/schema_introspect.py` parses `schema.sql` for expected columns + status/purpose CHECK values + one app-critical UNIQUE constraint, and diffs against the live catalog. (2) `GET /health/schema` serves that diff (200 in_sync / 503 drift). (3) A `deploy-migrate.yml` CI workflow applies the additive bootstrap to Supabase on push to master (pre-flight parser tests, post-flight live diff), and the existing `keepalive.yml` cron curls `/health/schema`.

**Tech Stack:** Python 3.12, FastAPI, psycopg3, Supabase Postgres (Supavisor pooler, port 6543), pytest, uv, GitHub Actions.

## Global Constraints

- **uv only** — run everything via `uv run …`; never `pip`/`venv`. (project CLAUDE.md)
- **Never f-string SQL** — parameterize or use `psycopg.sql`. (repo review rule)
- **Health-probe bodies carry no PII / no connection string / no stack trace** — generic messages only (T-06-02).
- **Free-tier** — no paid Render features (no `preDeployCommand`); Supabase reached via the pooler host on port 6543.
- **Additive migration only** — `bootstrap` runs WITHOUT `--reset`; never destructive in CI.
- **Catalog queries schema-qualified to `public`** — filter `table_schema='public'` / use `to_regclass('public.…')`.
- **Live constraint form is `CHECK ((<col> = ANY (ARRAY['v'::text, …])))`** — NOT `IN (...)`. Parsers of live output must handle `= ANY (ARRAY[...])` + strip `::text`.
- **Spec:** `docs/superpowers/specs/2026-07-07-live-schema-parity-check-design.md`.

---

### Task 1: `schema_introspect.expected_schema()` — parse `schema.sql`

**Files:**
- Create: `app/db/schema_introspect.py`
- Test: `tests/test_schema_introspect.py`

**Interfaces:**
- Consumes: `app/db/schema.sql` (read from disk).
- Produces:
  - `@dataclass(frozen=True) class ExpectedSchema: tables: dict[str, frozenset[str]]; status_values: frozenset[str]; purpose_values: frozenset[str]; unique_constraints: frozenset[str]`
  - `def expected_schema() -> ExpectedSchema` (reads `app/db/schema.sql`).
  - Internal helpers: `_columns_for_table(sql: str, table: str) -> set[str]`, `_do_block_check_values(sql: str, constraint_name: str, column: str) -> set[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schema_introspect.py
from app.db.schema_introspect import expected_schema


def test_expected_schema_columns_include_create_and_alter():
    exp = expected_schema()
    # CREATE-body column
    assert "status" in exp.tables["payroll_runs"]
    # Phase 11 columns (present in BOTH create + alter)
    assert "clarification_round" in exp.tables["payroll_runs"]
    assert "reply_epoch" in exp.tables["payroll_runs"]
    assert {"round", "consumed_round", "epoch"} <= exp.tables["email_messages"]
    # record_only is ALTER-ONLY in schema.sql (schema.sql:125) — proves the ALTER parse works
    assert "record_only" in exp.tables["payroll_runs"]


def test_expected_schema_excludes_table_constraints_as_columns():
    exp = expected_schema()
    cols = exp.tables["email_messages"]
    # constraint names / keywords must never be captured as columns
    assert "uq_email_run_purpose_round_epoch" not in cols
    assert "CONSTRAINT" not in cols
    assert "CHECK" not in cols
    assert "UNIQUE" not in cols


def test_expected_schema_check_and_unique_values():
    exp = expected_schema()
    assert "needs_operator" in exp.status_values
    assert "received" in exp.status_values
    assert "clarification_field_regression" in exp.purpose_values
    assert "uq_email_run_purpose_round_epoch" in exp.unique_constraints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema_introspect.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.schema_introspect'`

- [ ] **Step 3: Write the module**

```python
# app/db/schema_introspect.py
"""Parse app/db/schema.sql for the schema the app EXPECTS, and diff it against a
live database. Powers GET /health/schema and the deploy-migrate CI post-flight.

Scope (see spec): columns (CREATE + ALTER union), payroll_runs.status +
email_messages.purpose CHECK value sets (from the executable DO-block re-add
lists), and the one app-critical UNIQUE constraint uq_email_run_purpose_round_epoch.
NOT column types / NOT NULL / indexes (backlog).
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

_SCHEMA_SQL = pathlib.Path(__file__).parent / "schema.sql"

# Table-constraint leading keywords that must never be read as a column name.
_CONSTRAINT_KEYWORDS = frozenset(
    {"CONSTRAINT", "CHECK", "UNIQUE", "PRIMARY", "FOREIGN", "EXCLUDE"}
)

# The single app-critical UNIQUE constraint this check verifies exists live
# (the Phase-11 ON CONFLICT (run_id, purpose, round, epoch) arbiter).
_REQUIRED_UNIQUE_CONSTRAINTS = frozenset({"uq_email_run_purpose_round_epoch"})


@dataclass(frozen=True)
class ExpectedSchema:
    tables: dict[str, frozenset[str]]
    status_values: frozenset[str]
    purpose_values: frozenset[str]
    unique_constraints: frozenset[str]


def _strip_line_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _create_body(sql: str, table: str) -> str:
    """Return the parenthesized body of `CREATE TABLE [IF NOT EXISTS] <table> (...)`.

    Paren-balanced scan so nested parens (NUMERIC(12,2), CHECK (...)) don't end
    the body early.
    """
    m = re.search(
        rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{re.escape(table)}\s*\(",
        sql,
        re.IGNORECASE,
    )
    if not m:
        return ""
    depth = 0
    start = m.end() - 1  # at the opening '('
    for i in range(start, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return sql[start + 1 : i]
    return ""


def _split_top_level_commas(body: str) -> list[str]:
    """Split a CREATE-body on commas that are NOT inside parentheses."""
    items, depth, cur = [], 0, []
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        items.append("".join(cur))
    return items


def _columns_for_table(sql: str, table: str) -> set[str]:
    """Union of column names from the CREATE body AND ALTER ... ADD COLUMN lines."""
    cols: set[str] = set()

    # CREATE-body columns (first identifier of each top-level item that is not a
    # table-constraint clause).
    body = _create_body(sql, table)
    for item in _split_top_level_commas(body):
        tok = item.strip()
        if not tok:
            continue
        first = tok.split()[0].strip('"')
        if first.upper() in _CONSTRAINT_KEYWORDS:
            continue
        cols.add(first)

    # ALTER TABLE <table> ADD COLUMN [IF NOT EXISTS] <col> ...
    for m in re.finditer(
        rf"ALTER\s+TABLE\s+{re.escape(table)}\s+ADD\s+COLUMN\s+"
        rf"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        re.IGNORECASE,
    ):
        cols.add(m.group(1))

    return cols


def _do_block_check_values(sql: str, constraint_name: str, column: str) -> set[str]:
    """Parse the value list from the DO-block re-add `CHECK (<column> IN (...))`
    that appears AFTER the constraint-name literal (the executable definition —
    NOT the inline CREATE CHECK). Mirrors tests/test_status_drift.py's approach.
    """
    idx = sql.find(constraint_name)
    if idx == -1:
        raise ValueError(f"{constraint_name} not found in schema.sql")
    m = re.search(
        rf"CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\((.*?)\)\s*\)",
        sql[idx:],
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            f"No 'CHECK ({column} IN (...))' after {constraint_name} in schema.sql"
        )
    return {v.strip().strip("'") for v in m.group(1).split(",") if v.strip()}


def expected_schema() -> ExpectedSchema:
    sql = _strip_line_comments(_SCHEMA_SQL.read_text())
    tables = {
        "payroll_runs": frozenset(_columns_for_table(sql, "payroll_runs")),
        "email_messages": frozenset(_columns_for_table(sql, "email_messages")),
    }
    status_values = frozenset(
        _do_block_check_values(sql, "payroll_runs_status_check", "status")
    )
    purpose_values = frozenset(
        _do_block_check_values(sql, "email_messages_purpose_check", "purpose")
    )
    return ExpectedSchema(
        tables=tables,
        status_values=status_values,
        purpose_values=purpose_values,
        unique_constraints=_REQUIRED_UNIQUE_CONSTRAINTS,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_schema_introspect.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/db/schema_introspect.py tests/test_schema_introspect.py
git commit -m "feat(schema-parity): expected_schema() parser over schema.sql"
```

---

### Task 2: `schema_introspect.diff_against_live()` — diff vs live catalog

**Files:**
- Modify: `app/db/schema_introspect.py`
- Test: `tests/test_schema_introspect.py`

**Interfaces:**
- Consumes: `expected_schema()` (Task 1); a psycopg-like connection whose `.execute(sql, params).fetchall()` returns rows (satisfied by real psycopg AND `tests/conftest.py::FakeConnection`).
- Produces:
  - `@dataclass(frozen=True) class SchemaDiff: missing_columns: dict[str, list[str]]; missing_status_values: list[str]; missing_purpose_values: list[str]; missing_unique_constraints: list[str]` with a computed `@property is_in_sync -> bool` and `def as_missing_dict(self) -> dict[str, list[str]]` (drops empty keys — the endpoint body).
  - `def diff_against_live(conn) -> SchemaDiff`
  - `def _parse_any_array_values(constraintdef: str) -> set[str]` (parses the live `= ANY (ARRAY['v'::text, …])` form).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_schema_introspect.py
from app.db.schema_introspect import diff_against_live, _parse_any_array_values
from tests.conftest import FakeConnection  # existing test double


LIVE_STATUS_DEF = (
    "CHECK ((status = ANY (ARRAY['received'::text, 'extracting'::text, "
    "'awaiting_reply'::text, 'computed'::text, 'awaiting_approval'::text, "
    "'approved'::text, 'sent'::text, 'reconciled'::text, 'rejected'::text, "
    "'error'::text, 'needs_operator'::text])))"
)
LIVE_PURPOSE_DEF = (
    "CHECK ((purpose = ANY (ARRAY['clarification'::text, 'confirmation'::text, "
    "'clarification_field_regression'::text])))"
)


def test_parse_any_array_values_handles_live_form():
    vals = _parse_any_array_values(LIVE_STATUS_DEF)
    assert "needs_operator" in vals
    assert "received" in vals
    assert "::text" not in "".join(vals)  # casts stripped


def _script_in_sync(conn, *, drop_status=None, drop_col=None, drop_uq=False):
    """Script a FakeConnection to answer the 4 diff_against_live queries in order:
    1) payroll_runs columns  2) email_messages columns
    3) status+purpose constraint defs  4) unique-constraint names present.
    """
    from app.db.schema_introspect import expected_schema
    exp = expected_schema()
    pr_cols = set(exp.tables["payroll_runs"])
    em_cols = set(exp.tables["email_messages"])
    if drop_col:
        pr_cols.discard(drop_col)
    status_def = LIVE_STATUS_DEF
    if drop_status:
        status_def = status_def.replace(f", '{drop_status}'::text", "")
    uq_present = set() if drop_uq else {"uq_email_run_purpose_round_epoch"}
    conn.script_fetchall([(c,) for c in pr_cols])                 # Q1
    conn.script_fetchall([(c,) for c in em_cols])                 # Q2
    conn.script_fetchall([("status", status_def), ("purpose", LIVE_PURPOSE_DEF)])  # Q3
    conn.script_fetchall([(n,) for n in uq_present])              # Q4


def test_diff_in_sync():
    conn = FakeConnection()
    _script_in_sync(conn)
    diff = diff_against_live(conn)
    assert diff.is_in_sync
    assert diff.as_missing_dict() == {}


def test_diff_missing_column():
    conn = FakeConnection()
    _script_in_sync(conn, drop_col="clarification_round")
    diff = diff_against_live(conn)
    assert not diff.is_in_sync
    assert "clarification_round" in diff.missing_columns["payroll_runs"]


def test_diff_missing_status_value_live_form():
    conn = FakeConnection()
    _script_in_sync(conn, drop_status="needs_operator")
    diff = diff_against_live(conn)
    assert diff.missing_status_values == ["needs_operator"]


def test_diff_missing_unique_constraint():
    conn = FakeConnection()
    _script_in_sync(conn, drop_uq=True)
    diff = diff_against_live(conn)
    assert "uq_email_run_purpose_round_epoch" in diff.missing_unique_constraints


def test_diff_extra_live_column_is_not_drift():
    conn = FakeConnection()
    _script_in_sync(conn)
    # inject an extra column not in schema.sql into Q1's result
    conn._fetchall_q[0].append(("some_future_column",))
    diff = diff_against_live(conn)
    assert diff.is_in_sync  # extras are not drift
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema_introspect.py -k "diff or any_array" -v`
Expected: FAIL — `ImportError: cannot import name 'diff_against_live'`

- [ ] **Step 3: Implement the diff**

```python
# append to app/db/schema_introspect.py
from dataclasses import dataclass, field  # extend existing import line


@dataclass(frozen=True)
class SchemaDiff:
    missing_columns: dict[str, list[str]]
    missing_status_values: list[str]
    missing_purpose_values: list[str]
    missing_unique_constraints: list[str]

    @property
    def is_in_sync(self) -> bool:
        return not (
            any(self.missing_columns.values())
            or self.missing_status_values
            or self.missing_purpose_values
            or self.missing_unique_constraints
        )

    def as_missing_dict(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for tbl, cols in self.missing_columns.items():
            if cols:
                out[tbl] = sorted(cols)
        if self.missing_status_values:
            out["status_values"] = sorted(self.missing_status_values)
        if self.missing_purpose_values:
            out["purpose_values"] = sorted(self.missing_purpose_values)
        if self.missing_unique_constraints:
            out["unique_constraints"] = sorted(self.missing_unique_constraints)
        return out


def _parse_any_array_values(constraintdef: str) -> set[str]:
    """Parse values from the live form `CHECK ((col = ANY (ARRAY['v'::text, …])))`.
    Falls back to the `IN ('v', …)` form if present. Strips ::text casts + quotes.
    """
    m = re.search(r"ARRAY\s*\[(.*?)\]", constraintdef, re.DOTALL)
    if m is None:
        m = re.search(r"\bIN\s*\((.*?)\)", constraintdef, re.DOTALL)
    if m is None:
        return set()
    out = set()
    for raw in m.group(1).split(","):
        v = raw.strip()
        v = re.sub(r"::\w+$", "", v)   # strip ::text cast
        v = v.strip().strip("'")
        if v:
            out.add(v)
    return out


def _live_columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def diff_against_live(conn) -> SchemaDiff:
    exp = expected_schema()

    # Q1/Q2: columns per table.
    missing_columns: dict[str, list[str]] = {}
    for table, expected_cols in exp.tables.items():
        live = _live_columns(conn, table)
        missing_columns[table] = sorted(set(expected_cols) - live)

    # Q3: status + purpose CHECK defs (selected by conkey — column set — not name).
    rows = conn.execute(
        "SELECT CASE WHEN c.conrelid = to_regclass('public.payroll_runs') "
        "            THEN 'status' ELSE 'purpose' END AS which, "
        "       pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c "
        "WHERE c.contype = 'c' "
        "  AND c.conrelid IN (to_regclass('public.payroll_runs'), "
        "                     to_regclass('public.email_messages')) "
        "  AND (SELECT array_agg(a.attname::text) FROM pg_attribute a "
        "       WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)) "
        "      IN (ARRAY['status'], ARRAY['purpose'])",
    ).fetchall()
    live_status: set[str] = set()
    live_purpose: set[str] = set()
    for which, cdef in rows:
        if which == "status":
            live_status |= _parse_any_array_values(cdef)
        else:
            live_purpose |= _parse_any_array_values(cdef)
    missing_status = sorted(set(exp.status_values) - live_status)
    missing_purpose = sorted(set(exp.purpose_values) - live_purpose)

    # Q4: required unique constraints present on email_messages.
    rows = conn.execute(
        "SELECT conname FROM pg_constraint "
        "WHERE contype = 'u' AND conrelid = to_regclass('public.email_messages')",
    ).fetchall()
    live_uq = {r[0] for r in rows}
    missing_uq = sorted(set(exp.unique_constraints) - live_uq)

    return SchemaDiff(
        missing_columns=missing_columns,
        missing_status_values=missing_status,
        missing_purpose_values=missing_purpose,
        missing_unique_constraints=missing_uq,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema_introspect.py -v`
Expected: PASS (all tests, Task 1 + Task 2)

- [ ] **Step 5: Commit**

```bash
git add app/db/schema_introspect.py tests/test_schema_introspect.py
git commit -m "feat(schema-parity): diff_against_live() vs public catalog (ANY-ARRAY form)"
```

---

### Task 3: `GET /health/schema` endpoint

**Files:**
- Modify: `app/main.py` (add route after `health_ready`, ~line 273)
- Test: `tests/test_health_schema.py`

**Interfaces:**
- Consumes: `app.db.schema_introspect.diff_against_live` (Task 2); `app.db.supabase.get_connection` (existing context manager).
- Produces: `GET /health/schema` → `200 {"status":"in_sync"}` | `503 {"status":"drift","missing":{...}}` | `503 {"detail":"schema check unavailable"}` on DB/parse error.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_health_schema.py
from unittest.mock import patch
import contextlib
from fastapi.testclient import TestClient

from app.main import app
from app.db.schema_introspect import SchemaDiff
from tests.conftest import FakeConnection

client = TestClient(app)


@contextlib.contextmanager
def _fake_conn_cm(conn):
    yield conn


def test_health_schema_in_sync_returns_200():
    diff = SchemaDiff({}, [], [], [])  # nothing missing
    with patch("app.main.get_connection", lambda: _fake_conn_cm(FakeConnection())), \
         patch("app.main.diff_against_live", return_value=diff):
        r = client.get("/health/schema")
    assert r.status_code == 200
    assert r.json() == {"status": "in_sync"}


def test_health_schema_drift_returns_503_with_missing():
    diff = SchemaDiff({"payroll_runs": ["clarification_round"]}, ["needs_operator"], [], [])
    with patch("app.main.get_connection", lambda: _fake_conn_cm(FakeConnection())), \
         patch("app.main.diff_against_live", return_value=diff):
        r = client.get("/health/schema")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "drift"
    assert body["missing"]["payroll_runs"] == ["clarification_round"]
    assert body["missing"]["status_values"] == ["needs_operator"]


def test_health_schema_db_error_returns_503_no_leak():
    def _boom():
        raise RuntimeError("postgresql://user:secret@host/db unreachable")
    with patch("app.main.get_connection", _boom):
        r = client.get("/health/schema")
    assert r.status_code == 503
    assert "secret" not in r.text and "postgresql://" not in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_health_schema.py -v`
Expected: FAIL — 404 (route not defined) / import errors for `diff_against_live` in `app.main`.

- [ ] **Step 3: Add the route + imports**

In `app/main.py`, add these at **module level** (near the existing `from app.db import repo` on line 54) — NOT inside a function. The tests `patch("app.main.get_connection", …)` and `patch("app.main.diff_against_live", …)`, which require both names to be module-level attributes of `app.main`:

```python
from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection
```

Note: `health_ready` currently does a *function-local* `from app.db.supabase import get_connection` (line 265). Leave that as-is — it's harmless; the new module-level import is what the `/health/schema` route and its tests bind to. (`JSONResponse`, `HTTPException`, and `logger` are already imported/defined at module level — do not re-import them.)

Add the route immediately after the `health_ready` function (after ~line 273):

```python
@app.get("/health/schema")
def health_schema() -> JSONResponse:
    """Live schema-parity probe (columns + status/purpose CHECK values + the
    Phase-11 unique constraint) vs what schema.sql declares.

    200 {"status":"in_sync"}                       — live DB matches schema.sql
    503 {"status":"drift","missing":{...}}         — declared-but-missing on live
    503 {"detail":"schema check unavailable"}      — DB unreachable / parse error

    Body carries only schema identifier NAMES (no row data, no connection string,
    no stack trace) — same PII rule as /health/ready (T-06-02).
    """
    try:
        with get_connection() as conn:
            diff = diff_against_live(conn)
    except Exception as exc:  # noqa: BLE001 — probe must not leak internals
        logger.error("schema parity probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="schema check unavailable")
    if diff.is_in_sync:
        return JSONResponse({"status": "in_sync"})
    return JSONResponse(
        {"status": "drift", "missing": diff.as_missing_dict()},
        status_code=503,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_health_schema.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_health_schema.py
git commit -m "feat(schema-parity): GET /health/schema endpoint"
```

---

### Task 4: `app.db.check_schema` CLI (CI post-flight + manual use)

**Files:**
- Create: `app/db/check_schema.py`
- Test: `tests/test_check_schema_cli.py`

**Interfaces:**
- Consumes: `diff_against_live` (Task 2), `app.db.supabase.get_connection`.
- Produces: `python -m app.db.check_schema` → prints the diff, exits `0` if in-sync, `1` if drifted. `def main() -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_check_schema_cli.py
from unittest.mock import patch
import contextlib

from app.db.check_schema import main
from app.db.schema_introspect import SchemaDiff
from tests.conftest import FakeConnection


@contextlib.contextmanager
def _cm(conn):
    yield conn


def test_main_exits_0_in_sync(capsys):
    with patch("app.db.check_schema.get_connection", lambda: _cm(FakeConnection())), \
         patch("app.db.check_schema.diff_against_live", return_value=SchemaDiff({}, [], [], [])):
        assert main() == 0
    assert "in_sync" in capsys.readouterr().out


def test_main_exits_1_on_drift(capsys):
    diff = SchemaDiff({"payroll_runs": ["clarification_round"]}, [], [], [])
    with patch("app.db.check_schema.get_connection", lambda: _cm(FakeConnection())), \
         patch("app.db.check_schema.diff_against_live", return_value=diff):
        assert main() == 1
    assert "clarification_round" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_check_schema_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.check_schema'`

- [ ] **Step 3: Write the CLI**

```python
# app/db/check_schema.py
"""CLI wrapper over schema_introspect.diff_against_live for the deploy-migrate
CI post-flight step (and manual use). Exit 0 = in_sync, 1 = drift.

    uv run python -m app.db.check_schema
"""
from __future__ import annotations

import json
import sys

from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection


def main() -> int:
    with get_connection() as conn:
        diff = diff_against_live(conn)
    if diff.is_in_sync:
        print("schema check: in_sync")
        return 0
    print("schema check: DRIFT DETECTED")
    print(json.dumps(diff.as_missing_dict(), indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_check_schema_cli.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/db/check_schema.py tests/test_check_schema_cli.py
git commit -m "feat(schema-parity): app.db.check_schema CLI (exit 1 on drift)"
```

---

### Task 5: bootstrap sets `lock_timeout` / `statement_timeout`

**Files:**
- Modify: `app/db/bootstrap.py:96` (the `psycopg.connect(...)` block)
- Test: `tests/test_bootstrap_timeouts.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: bootstrap's admin connection issues `SET lock_timeout` + `SET statement_timeout` before any DDL, so a DDL blocked by the live app aborts (RED) instead of hanging CI. Exposes module constants `LOCK_TIMEOUT_MS = 10000`, `STATEMENT_TIMEOUT_MS = 60000` for the test to assert against.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap_timeouts.py
import app.db.bootstrap as bootstrap


def test_bootstrap_timeout_constants_defined():
    assert bootstrap.LOCK_TIMEOUT_MS == 10000
    assert bootstrap.STATEMENT_TIMEOUT_MS == 60000


def test_bootstrap_sets_timeouts_before_ddl(monkeypatch):
    executed: list[str] = []

    class _FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, *args, **kw): executed.append(str(sql)); return self
        def commit(self): pass

    monkeypatch.setattr(bootstrap.psycopg, "connect", lambda *a, **k: _FakeConn())
    monkeypatch.setattr(bootstrap, "get_settings", lambda: type("S", (), {"database_url": "postgresql://x/y"})())
    monkeypatch.setattr(bootstrap._SCHEMA_SQL, "read_text", lambda: "-- noop schema")

    bootstrap.bootstrap(reset=False)

    joined = "\n".join(executed)
    assert "lock_timeout" in joined
    assert "statement_timeout" in joined
    # timeouts must precede the schema apply
    assert joined.index("lock_timeout") < joined.index("noop schema")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bootstrap_timeouts.py -v`
Expected: FAIL — `AttributeError: module 'app.db.bootstrap' has no attribute 'LOCK_TIMEOUT_MS'`

- [ ] **Step 3: Add constants + SET statements**

In `app/db/bootstrap.py`, add near the top (after `_SCHEMA_SQL = ...`):

```python
# CI-safety (Codex #8): bound how long a DDL may wait on / hold a lock against the
# live app so lock contention fails RED instead of hanging the deploy-migrate job.
LOCK_TIMEOUT_MS = 10000        # 10s: abort if a DDL can't get its lock
STATEMENT_TIMEOUT_MS = 60000   # 60s: abort a single runaway statement
```

Inside `bootstrap()`, immediately after `with psycopg.connect(db_url, prepare_threshold=None) as conn:` (line 96) and before the `if reset:` block, insert:

```python
        # Bound lock/statement time on this admin connection (Codex #8) so a DDL
        # blocked by the live app aborts red rather than hanging CI. Session-level
        # SET; applies to every statement below on this connection.
        conn.execute(f"SET lock_timeout = '{LOCK_TIMEOUT_MS}ms'")
        conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'")
        conn.commit()
```

(Note: these are integer literals from trusted module constants formatted into a `SET` — not user input; the "never f-string SQL" rule targets untrusted values. `SET … = %s` is not supported by Postgres for these GUCs, so a literal is required.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bootstrap_timeouts.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/db/bootstrap.py tests/test_bootstrap_timeouts.py
git commit -m "feat(schema-parity): bootstrap sets lock_timeout/statement_timeout"
```

---

### Task 6: `deploy-migrate.yml` — migrate-on-merge CI

**Files:**
- Create: `.github/workflows/deploy-migrate.yml`

**Interfaces:**
- Consumes: `DATABASE_URL` Actions secret (already added by operator); `tests/test_schema_introspect.py` (Task 1/2); `app.db.bootstrap` (Task 5); `app.db.check_schema` (Task 4).
- Produces: on push to master, a green run = live Supabase in sync with `schema.sql`.

- [ ] **Step 1: Create the workflow**

```yaml
# .github/workflows/deploy-migrate.yml
name: deploy-migrate

# Prevention layer (spec Layer 2): apply schema.sql to live Supabase on merge to
# master so deployed code can't outrun its migration. Best-effort — runs in
# parallel with Render's auto-deploy (residual race covered by /health/schema +
# keepalive). Additive only (no --reset). Requires the DATABASE_URL secret.

on:
  push:
    branches: ["master"]
  workflow_dispatch:

jobs:
  migrate:
    name: "Apply additive migration to live Supabase"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"

      - name: Install deps (all groups)
        run: uv sync

      - name: Validate DATABASE_URL secret is set
        run: |
          if [ -z "$DATABASE_URL" ]; then
            echo "ERROR: DATABASE_URL secret is not set."
            echo "Add it at: Settings -> Secrets and variables -> Actions -> New secret"
            exit 1
          fi
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}

      - name: Pre-flight — schema-introspection parser tests (no DB)
        # A malformed schema.sql (bad CHECK/ALTER edit) fails HERE, before any DDL.
        run: uv run pytest tests/test_schema_introspect.py -q

      - name: Apply additive migration (no --reset)
        run: uv run python -m app.db.bootstrap
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}

      - name: Post-flight — verify live schema is in sync
        run: uv run python -m app.db.check_schema
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

- [ ] **Step 2: Validate the YAML parses**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-migrate.yml')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-migrate.yml
git commit -m "ci(schema-parity): deploy-migrate workflow (pre-flight tests, migrate, post-flight diff)"
```

---

### Task 7: keepalive curls `/health/schema`

**Files:**
- Modify: `.github/workflows/keepalive.yml` (add a step after the `/health/ready` ping)

**Interfaces:**
- Consumes: existing `RENDER_URL` secret; the deployed `/health/schema` (Task 3).
- Produces: a scheduled keep-alive run goes RED on live drift from ANY source.

- [ ] **Step 1: Add the step**

Append to the `ping` job's `steps:` in `.github/workflows/keepalive.yml`, after the existing "Ping Render health/ready" step:

```yaml
      - name: Check live schema parity (drift → RED)
        # Layer 3 monitoring: /health/schema returns 503 on drift; -f makes curl
        # exit non-zero so this scheduled run goes RED and the operator is notified.
        # Catches drift from ANY source, including a manual Supabase edit that
        # bypasses the deploy-migrate workflow (which only covers master merges).
        run: curl -f --max-time 90 "$RENDER_URL/health/schema"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```

- [ ] **Step 2: Validate the YAML parses**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/keepalive.yml')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/keepalive.yml
git commit -m "ci(schema-parity): keepalive curls /health/schema (drift → RED)"
```

---

### Task 8: Full-suite regression + live smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all pass, 0 regressions (new tests from Tasks 1–5 included).

- [ ] **Step 2: Lint**

Run: `uv run ruff check app/db/schema_introspect.py app/db/check_schema.py app/main.py app/db/bootstrap.py`
Expected: no errors.

- [ ] **Step 3: Live smoke against the real DB (local, has DATABASE_URL in .env)**

Run: `uv run python -m app.db.check_schema`
Expected: `schema check: in_sync` (the live DB was remediated already), exit 0.

- [ ] **Step 4: Commit (if lint auto-fixes anything; else skip)**

```bash
git add -A && git commit -m "chore(schema-parity): lint + verification pass" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- Layer 1 detection: Task 1 (`expected_schema`), Task 2 (`diff_against_live`), Task 3 (`/health/schema`). ✓
- Layer 2 prevention: Task 5 (bootstrap timeouts, Codex #8), Task 4 (`check_schema` post-flight, Codex #6), Task 6 (`deploy-migrate.yml` with pre-flight tests + post-flight diff + secret guard, Codex #6/#10). ✓
- Layer 3 monitoring: Task 7 (keepalive curl). ✓
- Codex #1 (ANY-ARRAY parse): Task 2 `_parse_any_array_values` + `test_parse_any_array_values_handles_live_form` / `test_diff_missing_status_value_live_form`. ✓
- Codex #2 (DO-block CHECK): Task 1 `_do_block_check_values`. ✓
- Codex #3 (paren-balanced column parser + `record_only` ALTER-only): Task 1 parser + `test_expected_schema_columns_include_create_and_alter` / `test_expected_schema_excludes_table_constraints_as_columns`. ✓
- Codex #4 (unique constraint): Task 1 `unique_constraints` + Task 2 Q4 + `test_diff_missing_unique_constraint`. ✓
- Codex #7 (schema-qualify public): Task 2 all queries use `table_schema='public'` / `to_regclass('public.…')`. ✓
- Codex #5 (honest prevention): documented in `deploy-migrate.yml` header comment. ✓
- "extras not drift": Task 2 `test_diff_extra_live_column_is_not_drift`. ✓
- No-PII probe body: Task 3 `test_health_schema_db_error_returns_503_no_leak`. ✓

**Placeholder scan:** none — every code/test step is complete.

**Type consistency:** `ExpectedSchema` / `SchemaDiff` field names (`tables`, `status_values`, `purpose_values`, `unique_constraints`, `missing_columns`, `missing_status_values`, `missing_purpose_values`, `missing_unique_constraints`, `is_in_sync`, `as_missing_dict`) are used identically across Tasks 1–4 and their tests. `diff_against_live(conn)` / `expected_schema()` / `main()` signatures match every call site.

**Operational note (not a code task):** the `DATABASE_URL` Actions secret is already added (operator confirmed). No pre-merge blocker remains.
