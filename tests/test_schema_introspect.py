# The schema checker accepts a runtime DB connection protocol; FakeConnection is
# the hermetic test double for that boundary.
from typing import Any, cast

import psycopg

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
    drop_col: str | None = None,
    drop_uq: bool = False,
) -> None:
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


def test_diff_missing_column():
    conn = FakeConnection()
    _script_in_sync(conn, drop_col="clarification_round")
    diff = _diff(conn)
    assert not diff.is_in_sync
    assert "clarification_round" in diff.missing_columns["payroll_runs"]


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


def test_diff_extra_live_column_is_not_drift():
    conn = FakeConnection()
    _script_in_sync(conn)
    # inject an extra column not in schema.sql into Q1's result
    conn._fetchall_q[0].append(("some_future_column",))
    diff = _diff(conn)
    assert diff.is_in_sync  # extras are not drift
