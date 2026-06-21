"""CI drift guard: SQL CHECK value sets must match their Python source of truth.

D-03: Python is the canonical source; schema.sql mirrors it.  Any value
enumerated in BOTH Python and a SQL CHECK is a drift risk — if one side gains or
loses a value, this test fails CI immediately.  No DB connection required.

Coverage (WR-09 — generalized from the original status-only guard):
- payroll_runs.status        ↔ RunStatus enum
- employees.pay_type         ↔ Employee.pay_type            Literal["hourly","salary"]
- employees.filing_status    ↔ Employee.filing_status       Literal[3 statuses]
- employees.pay_periods_per_year ↔ Employee.pay_periods_per_year Literal[12,24,26,52]

The Python side is read live via typing.get_args on the model field annotation
(not a hardcoded copy) so the test fails the moment a Literal changes without the
matching CHECK edit — exactly the drift the status guard already proved out.

Runs on every push with:
    pytest tests/test_status_drift.py -v
"""

import ast
import pathlib
import re
import typing

import pytest

from app.models.roster import Employee
from app.models.status import RunStatus

_SCHEMA_SQL = pathlib.Path(__file__).parent.parent / "app" / "db" / "schema.sql"


def _extract_check_in_values(sql: str, column: str) -> set[str]:
    """Parse the value set out of a `CHECK (<column> IN (...))` constraint.

    Generalized from the original status-only parser:
    1. Strip SQL line comments first (-- ...) so a commented-out old value
       cannot poison the regex match.
    2. Anchor the regex on the exact column name (re.escape) so a sibling
       column's CHECK (e.g. step_3_dependents >= 0) is never matched by
       accident — the original status test relied on this same anchoring.
    3. Split the CSV and strip whitespace + single quotes.  Numeric IN-lists
       (e.g. 12,24,26,52) have no quotes to strip, so the same normalization
       handles both string and integer enums and the result is always a
       set[str] for symmetric comparison.

    Returns the value set as strings; callers compare against str(...) of the
    Python source so quoted and unquoted SQL values compare uniformly.
    """
    # Strip line comments before regex (prevents ghost values).
    sql_clean = re.sub(r"--[^\n]*", "", sql)

    m = re.search(
        rf"CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\((.*?)\)\s*\)",
        sql_clean,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            f"No 'CHECK ({column} IN (...))' constraint found in schema.sql"
        )

    raw_values = m.group(1).split(",")
    return {v.strip().strip("'") for v in raw_values if v.strip()}


def _literal_values(field_name: str) -> set[str]:
    """Return the Literal arg set for an Employee field as strings.

    Read live from the model annotation via typing.get_args so a Literal change
    that is not mirrored in schema.sql fails this test (the preferred direction:
    the test follows the model, not a hardcoded copy).
    """
    annotation = Employee.model_fields[field_name].annotation
    return {str(arg) for arg in typing.get_args(annotation)}


# Dual-sourced enums: (schema column, Python value set).  status comes from the
# RunStatus enum; the three Employee fields come from their Literal annotations.
_DUAL_SOURCED_ENUMS = [
    ("status", {member.value for member in RunStatus}),
    ("pay_type", _literal_values("pay_type")),
    ("filing_status", _literal_values("filing_status")),
    ("pay_periods_per_year", _literal_values("pay_periods_per_year")),
]


class TestEnumCheckDrift:
    """schema.sql CHECK constraints must set-equal their Python source of truth."""

    def test_schema_file_exists(self) -> None:
        assert _SCHEMA_SQL.exists(), f"schema.sql not found at {_SCHEMA_SQL}"

    @pytest.mark.parametrize(
        "column, python_values",
        _DUAL_SOURCED_ENUMS,
        ids=[col for col, _ in _DUAL_SOURCED_ENUMS],
    )
    def test_check_values_match_python(
        self, column: str, python_values: set[str]
    ) -> None:
        """SQL CHECK value set equals the Python set — fails CI on drift."""
        sql = _SCHEMA_SQL.read_text()
        sql_values = _extract_check_in_values(sql, column)

        sql_only = sql_values - python_values
        py_only = python_values - sql_values

        assert sql_values == python_values, (
            f"Enum drift detected for column '{column}'!\n"
            f"  In SQL CHECK but not in Python: {sql_only or 'none'}\n"
            f"  In Python but not in SQL CHECK: {py_only or 'none'}\n"
            f"  SQL values:    {sorted(sql_values)}\n"
            f"  Python values: {sorted(python_values)}"
        )

    def test_status_exact_count_is_eleven(self) -> None:
        """Sanity-check that neither status source has silent duplicates."""
        sql = _SCHEMA_SQL.read_text()
        sql_values = _extract_check_in_values(sql, "status")
        enum_values = {member.value for member in RunStatus}

        assert len(sql_values) == 11, (
            f"Expected 11 unique status values in SQL CHECK, got {len(sql_values)}: "
            f"{sorted(sql_values)}"
        )
        assert len(enum_values) == 11, (
            f"Expected 11 RunStatus members, got {len(enum_values)}: "
            f"{sorted(enum_values)}"
        )

    def test_no_db_connection_needed(self) -> None:
        """Confirm the test file imports no DB module (pure static file test).

        Uses AST inspection of this file's own source to confirm no DB import
        exists.  Process-global sys.modules is NOT used (it would reflect other
        tests in the run, making the assertion order-dependent).
        """
        source = pathlib.Path(__file__).read_text()
        tree = ast.parse(source, filename=__file__)

        _FORBIDDEN = {"app.db.supabase", "psycopg", "psycopg_pool"}

        offenders: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN:
                        offenders.append(
                            f"line {node.lineno}: import {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in _FORBIDDEN or module.startswith("app.db.supabase"):
                    offenders.append(
                        f"line {node.lineno}: from {module} import ..."
                    )

        assert not offenders, (
            "test_status_drift.py must not import the DB layer.\n"
            "Forbidden import(s) found:\n  " + "\n  ".join(offenders)
        )
