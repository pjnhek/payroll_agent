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
