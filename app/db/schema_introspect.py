"""Parse app/db/schema.sql for the schema the app EXPECTS, and diff it against a
live database. Powers GET /health/schema and the deploy-migrate CI post-flight.

Scope (see spec): columns (CREATE + ALTER union), payroll_runs.status +
email_messages.purpose CHECK value sets (from the executable DO-block re-add
lists), the app-critical UNIQUE constraint uq_email_run_purpose_round_epoch,
and the narrow named index/constraint inventory required by typed operator
resume persistence. NOT general column types / NOT NULL / index coverage.
"""
from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

import psycopg

_SCHEMA_SQL = pathlib.Path(__file__).parent / "schema.sql"

# Table-constraint leading keywords that must never be read as a column name.
_CONSTRAINT_KEYWORDS = frozenset(
    {"CONSTRAINT", "CHECK", "UNIQUE", "PRIMARY", "FOREIGN", "EXCLUDE"}
)

# The single app-critical UNIQUE constraint this check verifies exists live
# (the Phase-11 ON CONFLICT (run_id, purpose, round, epoch) arbiter).
_REQUIRED_UNIQUE_CONSTRAINTS = frozenset({"uq_email_run_purpose_round_epoch"})

ColumnSpec = tuple[str, bool]
IndexSpec = tuple[str, tuple[str, ...], bool, str | None]
ConstraintSpec = tuple[
    str,
    str,
    tuple[str, ...],
    str | None,
    tuple[str, ...],
    str | None,
    str | None,
]
TriggerSpec = tuple[str, str, str, bool, bool]

_REQUIRED_COLUMN_SPECS: dict[tuple[str, str], ColumnSpec] = {
    ("inbound_events", "id"): ("uuid", False),
    ("inbound_events", "external_event_id"): ("text", False),
    ("inbound_events", "payload"): ("jsonb", False),
    ("inbound_events", "received_at"): ("timestamp with time zone", False),
    ("jobs", "event_id"): ("uuid", True),
    ("operator_resume_resolutions", "authoritative"): ("boolean", False),
    ("operator_resume_resolutions", "superseded_by"): ("uuid", True),
    ("operator_resume_overrides", "remember"): ("boolean", False),
    ("operator_resolution_writer_fence", "singleton"): ("boolean", False),
    ("operator_resolution_writer_fence", "writes_open"): ("boolean", False),
}

# These are the relationships schema health must prove before queue handlers
# depend on typed operator resolution persistence. Checking the complete catalog
# shape prevents a same-named but malformed index/constraint from passing.
_REQUIRED_INDEXES: dict[str, IndexSpec] = {
    "idx_operator_resume_resolutions_run_id": (
        "operator_resume_resolutions",
        ("run_id",),
        False,
        None,
    ),
    "idx_inbound_events_received_at": (
        "inbound_events",
        ("received_at",),
        False,
        None,
    ),
    "uq_operator_resume_authoritative_run": (
        "operator_resume_resolutions",
        ("run_id",),
        True,
        "authoritative",
    ),
}
_REQUIRED_CONSTRAINTS: dict[str, ConstraintSpec] = {
    "fk_jobs_operator_resolution": (
        "jobs",
        "f",
        ("operator_resolution_id",),
        "operator_resume_resolutions",
        ("id",),
        "a",
        None,
    ),
    "fk_jobs_inbound_event": (
        "jobs",
        "f",
        ("event_id",),
        "inbound_events",
        ("id",),
        "n",
        None,
    ),
    "operator_resume_overrides_pkey": (
        "operator_resume_overrides",
        "p",
        ("operator_resolution_id", "submitted_name"),
        None,
        (),
        None,
        None,
    ),
    "operator_resume_overrides_operator_resolution_id_fkey": (
        "operator_resume_overrides",
        "f",
        ("operator_resolution_id",),
        "operator_resume_resolutions",
        ("id",),
        "a",
        None,
    ),
    "operator_resume_overrides_employee_id_fkey": (
        "operator_resume_overrides",
        "f",
        ("employee_id",),
        "employees",
        ("id",),
        "a",
        None,
    ),
    "fk_operator_resume_superseded_by": (
        "operator_resume_resolutions",
        "f",
        ("superseded_by",),
        "operator_resume_resolutions",
        ("id",),
        "a",
        None,
    ),
    "uq_inbound_events_external_event_id": (
        "inbound_events",
        "u",
        ("external_event_id",),
        None,
        (),
        None,
        None,
    ),
    "operator_resolution_writer_fence_pkey": (
        "operator_resolution_writer_fence",
        "p",
        ("singleton",),
        None,
        (),
        None,
        None,
    ),
    "ck_operator_resolution_writer_fence_singleton": (
        "operator_resolution_writer_fence",
        "c",
        ("singleton",),
        None,
        (),
        None,
        "CHECK (singleton)",
    ),
}
_REQUIRED_TRIGGERS: dict[str, TriggerSpec] = {
    "trg_operator_resolution_writer_fence": (
        "operator_resume_resolutions",
        "enforce_operator_resolution_writer_fence",
        "O",
        True,
        True,
    )
}


@dataclass(frozen=True)
class ExpectedSchema:
    tables: dict[str, frozenset[str]]
    status_values: frozenset[str]
    purpose_values: frozenset[str]
    unique_constraints: frozenset[str]
    required_indexes: dict[str, IndexSpec]
    required_constraints: dict[str, ConstraintSpec]
    required_column_specs: dict[tuple[str, str], ColumnSpec]
    required_triggers: dict[str, TriggerSpec]


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
        "inbound_events": frozenset(_columns_for_table(sql, "inbound_events")),
        "operator_resume_resolutions": frozenset(
            _columns_for_table(sql, "operator_resume_resolutions")
        ),
        "operator_resume_overrides": frozenset(
            _columns_for_table(sql, "operator_resume_overrides")
        ),
        "operator_resolution_writer_fence": frozenset(
            _columns_for_table(sql, "operator_resolution_writer_fence")
        ),
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
        required_indexes=dict(_REQUIRED_INDEXES),
        required_constraints=dict(_REQUIRED_CONSTRAINTS),
        required_column_specs=dict(_REQUIRED_COLUMN_SPECS),
        required_triggers=dict(_REQUIRED_TRIGGERS),
    )


@dataclass(frozen=True)
class SchemaDiff:
    missing_columns: dict[str, list[str]]
    missing_status_values: list[str]
    missing_purpose_values: list[str]
    missing_unique_constraints: list[str]
    missing_required_indexes: list[str] = field(default_factory=list)
    missing_required_constraints: list[str] = field(default_factory=list)
    missing_required_columns: list[str] = field(default_factory=list)
    missing_required_triggers: list[str] = field(default_factory=list)

    @property
    def is_in_sync(self) -> bool:
        return not (
            any(self.missing_columns.values())
            or self.missing_status_values
            or self.missing_purpose_values
            or self.missing_unique_constraints
            or self.missing_required_indexes
            or self.missing_required_constraints
            or self.missing_required_columns
            or self.missing_required_triggers
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
        if self.missing_required_indexes:
            out["required_indexes"] = sorted(self.missing_required_indexes)
        if self.missing_required_constraints:
            out["required_constraints"] = sorted(self.missing_required_constraints)
        if self.missing_required_columns:
            out["required_columns"] = sorted(self.missing_required_columns)
        if self.missing_required_triggers:
            out["required_triggers"] = sorted(self.missing_required_triggers)
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


def _live_columns(conn: psycopg.Connection, table: str) -> dict[str, ColumnSpec]:
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return {name: (data_type, nullable == "YES") for name, data_type, nullable in rows}


def diff_against_live(conn: psycopg.Connection) -> SchemaDiff:
    exp = expected_schema()

    # Q1-Q5: columns per table, in ExpectedSchema.tables insertion order.
    missing_columns: dict[str, list[str]] = {}
    live_columns: dict[tuple[str, str], ColumnSpec] = {}
    for table, expected_cols in exp.tables.items():
        live = _live_columns(conn, table)
        missing_columns[table] = sorted(set(expected_cols) - set(live))
        live_columns.update(((table, name), spec) for name, spec in live.items())
    missing_required_columns = sorted(
        f"{table}.{column}"
        for (table, column), spec in exp.required_column_specs.items()
        if live_columns.get((table, column)) != spec
    )

    # Q6: status + purpose CHECK defs (selected by conkey — column set — not name).
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

    # Q7: required unique constraints present on email_messages.
    rows = conn.execute(
        "SELECT conname FROM pg_constraint "
        "WHERE contype = 'u' AND conrelid = to_regclass('public.email_messages')",
    ).fetchall()
    live_uq = {r[0] for r in rows}
    missing_uq = sorted(set(exp.unique_constraints) - live_uq)

    # Q8: named operator-resolution indexes, including exact owning table and
    # ordered key columns. A matching name alone is not sufficient.
    rows = conn.execute(
        "SELECT idx.relname, tbl.relname, "
        "       array_agg(a.attname ORDER BY key.ordinality), "
        "       i.indisunique, pg_get_expr(i.indpred, i.indrelid) "
        "FROM pg_index i "
        "JOIN pg_class idx ON idx.oid = i.indexrelid "
        "JOIN pg_class tbl ON tbl.oid = i.indrelid "
        "JOIN pg_namespace ns ON ns.oid = tbl.relnamespace "
        "CROSS JOIN LATERAL "
        "     unnest(i.indkey::smallint[]) WITH ORDINALITY "
        "     AS key(attnum, ordinality) "
        "JOIN pg_attribute a ON a.attrelid = tbl.oid AND a.attnum = key.attnum "
        "WHERE ns.nspname = 'public' AND idx.relname = ANY (%s) "
        "GROUP BY idx.relname, tbl.relname, i.indisunique, i.indpred, i.indrelid",
        (sorted(exp.required_indexes),),
    ).fetchall()
    live_indexes: dict[str, IndexSpec] = {
        name: (table, tuple(columns), unique, predicate)
        for name, table, columns, unique, predicate in rows
    }
    missing_indexes = sorted(
        name
        for name, spec in exp.required_indexes.items()
        if live_indexes.get(name) != spec
    )

    # Q9: named typed-resolution constraints with exact local and referenced
    # table/column shapes. This detects both absence and malformed relationships.
    rows = conn.execute(
        "SELECT c.conname, rel.relname, c.contype, "
        "       ARRAY(SELECT a.attname "
        "             FROM unnest(c.conkey) WITH ORDINALITY AS key(attnum, ordinality) "
        "             JOIN pg_attribute a "
        "               ON a.attrelid = c.conrelid AND a.attnum = key.attnum "
        "             ORDER BY key.ordinality), "
        "       ref.relname, "
        "       ARRAY(SELECT a.attname "
        "             FROM unnest(c.confkey) WITH ORDINALITY AS key(attnum, ordinality) "
        "             JOIN pg_attribute a "
        "               ON a.attrelid = c.confrelid AND a.attnum = key.attnum "
        "             ORDER BY key.ordinality), "
        "       CASE WHEN c.contype = 'f' THEN c.confdeltype::text ELSE NULL END, "
        "       CASE WHEN c.contype = 'c' THEN pg_get_constraintdef(c.oid) ELSE NULL END "
        "FROM pg_constraint c "
        "JOIN pg_class rel ON rel.oid = c.conrelid "
        "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
        "LEFT JOIN pg_class ref ON ref.oid = c.confrelid "
        "WHERE ns.nspname = 'public' AND c.conname = ANY (%s)",
        (sorted(exp.required_constraints),),
    ).fetchall()
    live_constraints: dict[str, ConstraintSpec] = {
        name: (
            table,
            kind,
            tuple(columns),
            ref_table,
            tuple(ref_columns),
            delete_action,
            definition,
        )
        for (
            name,
            table,
            kind,
            columns,
            ref_table,
            ref_columns,
            delete_action,
            definition,
        ) in rows
    }
    missing_constraints = sorted(
        name
        for name, spec in exp.required_constraints.items()
        if live_constraints.get(name) != spec
    )

    rows = conn.execute(
        "SELECT t.tgname, rel.relname, p.proname, t.tgenabled, "
        "       (t.tgtype & 2) <> 0 AS is_before, "
        "       (t.tgtype & 4) <> 0 AS fires_on_insert "
        "FROM pg_trigger t "
        "JOIN pg_class rel ON rel.oid = t.tgrelid "
        "JOIN pg_namespace ns ON ns.oid = rel.relnamespace "
        "JOIN pg_proc p ON p.oid = t.tgfoid "
        "WHERE NOT t.tgisinternal AND ns.nspname = 'public' "
        "  AND t.tgname = ANY (%s)",
        (sorted(exp.required_triggers),),
    ).fetchall()
    live_triggers: dict[str, TriggerSpec] = {
        name: (table, function, enabled, before, insert)
        for name, table, function, enabled, before, insert in rows
    }
    missing_triggers = sorted(
        name
        for name, spec in exp.required_triggers.items()
        if live_triggers.get(name) != spec
    )

    return SchemaDiff(
        missing_columns=missing_columns,
        missing_status_values=missing_status,
        missing_purpose_values=missing_purpose,
        missing_unique_constraints=missing_uq,
        missing_required_indexes=missing_indexes,
        missing_required_constraints=missing_constraints,
        missing_required_columns=missing_required_columns,
        missing_required_triggers=missing_triggers,
    )
