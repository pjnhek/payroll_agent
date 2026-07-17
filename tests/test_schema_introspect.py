# The schema checker accepts a runtime DB connection protocol; FakeConnection is
# the hermetic test double for that boundary.
import pathlib
from typing import Any, cast

import psycopg
import pytest

from app.db.schema_introspect import (
    SchemaDiff,
    _create_body,
    _parse_any_array_values,
    _strip_line_comments,
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
    assert {"operator_resolution_id", "event_id"} <= exp.tables["jobs"]
    assert exp.tables["inbound_events"] == frozenset(
        {"id", "external_event_id", "payload", "received_at"}
    )
    assert exp.tables["operator_resume_resolutions"] == frozenset(
        {"id", "run_id", "authoritative", "superseded_by", "created_at"}
    )
    assert exp.tables["operator_resume_overrides"] == frozenset(
        {
            "operator_resolution_id",
            "submitted_name",
            "employee_id",
            "remember",
            "created_at",
        }
    )
    assert exp.tables["operator_resolution_writer_fence"] == frozenset(
        {"singleton", "writes_open", "updated_at"}
    )


def test_expected_schema_phase19_column_types_are_exact():
    exp = expected_schema()
    assert exp.required_column_specs == {
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
    assert exp.required_constraints == {
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
    assert exp.required_triggers == {
        "trg_operator_resolution_writer_fence": (
            "operator_resume_resolutions",
            "enforce_operator_resolution_writer_fence",
            "O",
            True,
            True,
        )
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
    drop_trigger: str | None = None,
    malformed_trigger: str | None = None,
    malformed_column: tuple[str, str] | None = None,
) -> None:
    """Script the durable-receipt and authority diff queries in explicit order.

    The first queries fetch one typed column set per expected table in insertion
    order. The final queries fetch status/purpose checks, legacy unique constraints,
    required named indexes, constraints, and triggers respectively.
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
        rows = []
        for column in live_tables[table]:
            spec = exp.required_column_specs.get((table, column))
            data_type, nullable = spec if spec is not None else ("text", True)
            if malformed_column == (table, column):
                data_type = "text" if data_type != "text" else "uuid"
            rows.append((column, data_type, "YES" if nullable else "NO"))
        conn.script_fetchall(rows)
    conn.script_fetchall([("status", status_def), ("purpose", LIVE_PURPOSE_DEF)])
    conn.script_fetchall([(name,) for name in uq_present])

    index_rows = [
        (name, table, list(columns), unique, predicate)
        for name, (table, columns, unique, predicate) in exp.required_indexes.items()
        if name != drop_index
    ]
    if malformed_index:
        index_rows = [
            (
                name,
                table,
                ["created_at"] if name == malformed_index else columns,
                unique,
                predicate,
            )
            for name, table, columns, unique, predicate in index_rows
        ]
    conn.script_fetchall(index_rows)

    constraint_rows = [
        (
            name,
            table,
            kind,
            list(columns),
            ref_table,
            list(ref_columns),
            delete_action,
            definition,
        )
        for name, (
            table,
            kind,
            columns,
            ref_table,
            ref_columns,
            delete_action,
            definition,
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
            ) in constraint_rows
        ]
    conn.script_fetchall(constraint_rows)

    trigger_rows = [
        (name, table, function, enabled, before, insert)
        for name, (table, function, enabled, before, insert) in exp.required_triggers.items()
        if name != drop_trigger
    ]
    if malformed_trigger:
        trigger_rows = [
            (
                name,
                table,
                "wrong_function" if name == malformed_trigger else function,
                enabled,
                before,
                insert,
            )
            for name, table, function, enabled, before, insert in trigger_rows
        ]
    conn.script_fetchall(trigger_rows)


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
    expected_query_count = len(expected_schema().tables) + 5
    assert len(conn.executed) == expected_query_count
    assert [params for _, params in conn.executed[: len(expected_schema().tables)]] == [
        (table,) for table in expected_schema().tables
    ]
    assert "pg_index" in str(conn.executed[-3][0])
    assert "pg_constraint" in str(conn.executed[-2][0])
    assert "pg_trigger" in str(conn.executed[-1][0])


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


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("inbound_events", "payload"),
        ("jobs", "event_id"),
        ("operator_resume_resolutions", "authoritative"),
        ("operator_resume_overrides", "remember"),
        ("operator_resolution_writer_fence", "writes_open"),
    ],
)
def test_diff_rejects_malformed_phase19_column_type(table: str, column: str):
    conn = FakeConnection()
    _script_in_sync(conn, malformed_column=(table, column))
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert f"{table}.{column}" in diff.missing_required_columns


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
    name = "uq_operator_resume_authoritative_run"
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
    name = "fk_jobs_inbound_event"
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


@pytest.mark.parametrize("malformed", [False, True])
def test_diff_missing_or_malformed_writer_fence_trigger(malformed: bool):
    name = "trg_operator_resolution_writer_fence"
    conn = FakeConnection()
    _script_in_sync(
        conn,
        drop_trigger=None if malformed else name,
        malformed_trigger=name if malformed else None,
    )
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert diff.missing_required_triggers == [name]
    assert diff.as_missing_dict()["required_triggers"] == [name]


def test_bootstrap_reset_drops_jobs_before_inbound_events():
    from app.db import bootstrap

    assert bootstrap._DROP_ORDER.index("jobs") < bootstrap._DROP_ORDER.index(
        "inbound_events"
    )


def test_schema_reapply_never_reopens_closed_writer_fence():
    schema = pathlib.Path("app/db/schema.sql").read_text()
    fence_seed = schema.split(
        "INSERT INTO operator_resolution_writer_fence", 1
    )[1].split("CREATE OR REPLACE FUNCTION", 1)[0]
    assert "ON CONFLICT (singleton) DO NOTHING" in fence_seed
    assert "UPDATE" not in fence_seed.upper()


def test_phase19_columns_exist_in_fresh_and_additive_paths():
    schema = pathlib.Path("app/db/schema.sql").read_text()
    clean = _strip_line_comments(schema)
    assert "event_id" in _create_body(clean, "jobs")
    assert "authoritative" in _create_body(clean, "operator_resume_resolutions")
    assert "remember" in _create_body(clean, "operator_resume_overrides")
    for statement in (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS event_id UUID",
        "ADD COLUMN IF NOT EXISTS authoritative BOOLEAN NOT NULL DEFAULT FALSE",
        "ADD COLUMN IF NOT EXISTS superseded_by UUID",
        "ADD COLUMN IF NOT EXISTS remember BOOLEAN NOT NULL DEFAULT FALSE",
    ):
        assert statement in clean


def test_diff_extra_live_column_is_not_drift():
    conn = FakeConnection()
    _script_in_sync(conn)
    # inject an extra column not in schema.sql into Q1's result
    conn._fetchall_q[0].append(("some_future_column", "text", "YES"))
    diff = _diff(conn)
    assert diff.is_in_sync  # extras are not drift
