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

import psycopg

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
    items: list[str] = []
    depth = 0
    cur: list[str] = []
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
        # Column coverage only — NOT the Q3 CHECK-value drift query below.
        # jobs.kind/jobs.state are declared as INLINE CHECKs inside CREATE TABLE
        # jobs (...), not via the DO-block re-add pattern _do_block_check_values
        # parses, so feeding them through that parser raises ValueError. Their
        # value-drift coverage lives in tests/test_job_kind_drift.py's own
        # inline-CHECK parser instead. What this line buys is narrower: a `jobs`
        # table that silently failed to apply on a live deploy now trips
        # /health/schema instead of the endpoint reporting in_sync with the
        # newest, most concurrency-critical table entirely unchecked.
        "jobs": frozenset(_columns_for_table(sql, "jobs")),
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


def _live_columns(conn: psycopg.Connection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


def diff_against_live(conn: psycopg.Connection) -> SchemaDiff:
    exp = expected_schema()

    # Q1/Q2: columns per table.
    missing_columns: dict[str, list[str]] = {}
    for table, expected_cols in exp.tables.items():
        live = _live_columns(conn, table)
        missing_columns[table] = sorted(set(expected_cols) - live)

    # Q3: status + purpose CHECK defs (selected by conkey — column set — not name).
    # Deliberately still exactly these two tables. The CASE WHEN below can only
    # express a binary choice, so a third table needs a genuinely different query
    # shape, not a wider IN list — and jobs.kind/jobs.state have no DO-block
    # constraint-name literal to anchor a third branch on in the first place
    # (see the comment on expected_schema()'s "jobs" entry above).
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
