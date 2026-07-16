# The schema checker accepts a runtime DB connection protocol; FakeConnection is
# the hermetic test double for that boundary.
from typing import Any, cast

import psycopg
import pytest

from app.db.schema_introspect import (
    SchemaDiff,
    _parse_any_array_values,
    diff_against_live,
    expected_schema,
)
from tests.conftest import FakeConnection  # existing test double


def test_expected_schema_columns_include_create_and_alter():
    exp = expected_schema()
    # CREATE-body column
    assert "status" in exp.tables["payroll_runs"]
    # Clarification-round columns (present in BOTH create + alter)
    assert "clarification_round" in exp.tables["payroll_runs"]
    assert "reply_epoch" in exp.tables["payroll_runs"]
    assert {"round", "consumed_round", "epoch"} <= exp.tables["email_messages"]
    # record_only is ALTER-ONLY in schema.sql (schema.sql:125) — proves the ALTER parse works
    assert "record_only" in exp.tables["payroll_runs"]
    assert "operator_resolution_id" in exp.tables["jobs"]
    assert exp.tables["operator_resume_resolutions"] == frozenset(
        {"id", "run_id", "created_at"}
    )
    assert exp.tables["operator_resume_overrides"] == frozenset(
        {"operator_resolution_id", "submitted_name", "employee_id", "created_at"}
    )


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
    assert exp.required_indexes == {
        "idx_operator_resume_resolutions_run_id": (
            "operator_resume_resolutions",
            ("run_id",),
        )
    }
    assert exp.required_constraints == {
        "fk_jobs_operator_resolution": (
            "jobs",
            "f",
            ("operator_resolution_id",),
            "operator_resume_resolutions",
            ("id",),
        ),
        "operator_resume_overrides_pkey": (
            "operator_resume_overrides",
            "p",
            ("operator_resolution_id", "submitted_name"),
            None,
            (),
        ),
        "operator_resume_overrides_operator_resolution_id_fkey": (
            "operator_resume_overrides",
            "f",
            ("operator_resolution_id",),
            "operator_resume_resolutions",
            ("id",),
        ),
        "operator_resume_overrides_employee_id_fkey": (
            "operator_resume_overrides",
            "f",
            ("employee_id",),
            "employees",
            ("id",),
        ),
    }


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


def _script_in_sync(
    conn: FakeConnection,
    *,
    drop_status: str | None = None,
    drop_column: tuple[str, str] | None = None,
    drop_table: str | None = None,
    drop_uq: bool = False,
    drop_index: str | None = None,
    malformed_index: str | None = None,
    drop_constraint: str | None = None,
    malformed_constraint: str | None = None,
) -> None:
    """Script the 9 diff_against_live queries in their explicit order.

    Queries 1-5 fetch one column set for each expected table in insertion order.
    Queries 6-9 fetch status/purpose checks, legacy unique constraints, required
    named indexes, and required named constraints respectively.
    """
    from app.db.schema_introspect import expected_schema

    exp = expected_schema()
    live_tables = {table: set(columns) for table, columns in exp.tables.items()}
    if drop_table:
        live_tables[drop_table].clear()
    if drop_column:
        table, column = drop_column
        live_tables[table].discard(column)
    status_def = LIVE_STATUS_DEF
    if drop_status:
        status_def = status_def.replace(f", '{drop_status}'::text", "")
    uq_present = set() if drop_uq else {"uq_email_run_purpose_round_epoch"}
    for table in exp.tables:
        conn.script_fetchall([(column,) for column in live_tables[table]])
    conn.script_fetchall([("status", status_def), ("purpose", LIVE_PURPOSE_DEF)])
    conn.script_fetchall([(name,) for name in uq_present])

    index_rows = [
        (name, table, list(columns))
        for name, (table, columns) in exp.required_indexes.items()
        if name != drop_index
    ]
    if malformed_index:
        index_rows = [
            (name, table, ["created_at"] if name == malformed_index else columns)
            for name, table, columns in index_rows
        ]
    conn.script_fetchall(index_rows)

    constraint_rows = [
        (name, table, kind, list(columns), ref_table, list(ref_columns))
        for name, (
            table,
            kind,
            columns,
            ref_table,
            ref_columns,
        ) in exp.required_constraints.items()
        if name != drop_constraint
    ]
    if malformed_constraint:
        constraint_rows = [
            (
                name,
                table,
                kind,
                columns,
                "businesses" if name == malformed_constraint else ref_table,
                ref_columns,
            )
            for name, table, kind, columns, ref_table, ref_columns in constraint_rows
        ]
    conn.script_fetchall(constraint_rows)


def _diff(conn: FakeConnection) -> SchemaDiff:
    """diff_against_live over the hermetic FakeConnection test double.

    FakeConnection duck-types the cursor surface diff_against_live uses; the
    cast bridges it to the psycopg.Connection annotation at this one seam.
    """
    return diff_against_live(cast("psycopg.Connection[tuple[Any, ...]]", conn))


def test_diff_in_sync():
    conn = FakeConnection()
    _script_in_sync(conn)
    diff = _diff(conn)
    assert diff.is_in_sync
    assert diff.as_missing_dict() == {}
    assert len(conn.executed) == 9
    assert [params for _, params in conn.executed[:5]] == [
        (table,) for table in expected_schema().tables
    ]
    assert "pg_index" in str(conn.executed[7][0])
    assert "pg_constraint" in str(conn.executed[8][0])


def test_diff_missing_column():
    conn = FakeConnection()
    _script_in_sync(conn, drop_column=("payroll_runs", "clarification_round"))
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert "clarification_round" in diff.missing_columns["payroll_runs"]


@pytest.mark.parametrize(
    "table", ["operator_resume_resolutions", "operator_resume_overrides"]
)
def test_diff_missing_operator_resume_table(table: str):
    conn = FakeConnection()
    _script_in_sync(conn, drop_table=table)
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert diff.missing_columns[table] == sorted(expected_schema().tables[table])


def test_diff_missing_operator_resolution_key_column():
    conn = FakeConnection()
    _script_in_sync(conn, drop_column=("jobs", "operator_resolution_id"))
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert diff.missing_columns["jobs"] == ["operator_resolution_id"]


def test_diff_missing_status_value_live_form():
    conn = FakeConnection()
    _script_in_sync(conn, drop_status="needs_operator")
    diff = _diff(conn)
    assert diff.missing_status_values == ["needs_operator"]


def test_diff_missing_unique_constraint():
    conn = FakeConnection()
    _script_in_sync(conn, drop_uq=True)
    diff = _diff(conn)
    assert "uq_email_run_purpose_round_epoch" in diff.missing_unique_constraints


@pytest.mark.parametrize("malformed", [False, True])
def test_diff_missing_or_malformed_required_index(malformed: bool):
    name = "idx_operator_resume_resolutions_run_id"
    conn = FakeConnection()
    _script_in_sync(
        conn,
        drop_index=None if malformed else name,
        malformed_index=name if malformed else None,
    )
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert diff.missing_required_indexes == [name]
    assert diff.as_missing_dict()["required_indexes"] == [name]


@pytest.mark.parametrize("malformed", [False, True])
def test_diff_missing_or_malformed_required_constraint(malformed: bool):
    name = "operator_resume_overrides_employee_id_fkey"
    conn = FakeConnection()
    _script_in_sync(
        conn,
        drop_constraint=None if malformed else name,
        malformed_constraint=name if malformed else None,
    )
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert diff.missing_required_constraints == [name]
    assert diff.as_missing_dict()["required_constraints"] == [name]


def test_diff_extra_live_column_is_not_drift():
    conn = FakeConnection()
    _script_in_sync(conn)
    # inject an extra column not in schema.sql into Q1's result
    conn._fetchall_q[0].append(("some_future_column",))
    diff = _diff(conn)
    assert diff.is_in_sync  # extras are not drift
