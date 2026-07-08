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
