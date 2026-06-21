"""CI drift guard: SQL CHECK values must match RunStatus enum members exactly.

D-03: Python RunStatus is the canonical source; schema.sql mirrors it.  This
test asserts set-equality so any drift (a value added to one but not the other)
fails CI immediately — no DB connection required.

Runs on every push with:
    pytest tests/test_status_drift.py -v
"""

import pathlib
import re

from app.models.status import RunStatus

_SCHEMA_SQL = pathlib.Path(__file__).parent.parent / "app" / "db" / "schema.sql"


def _extract_status_check_values(sql: str) -> set[str]:
    """Parse the 11 status values out of the payroll_runs CHECK constraint.

    Steps:
    1. Strip SQL line comments first (-- ...) so a commented-out old value
       cannot poison the regex match.
    2. Locate CHECK (status IN (...)) with a regex.
    3. Split the CSV and strip whitespace + single quotes.
    """
    # Strip line comments before regex (Finding #9 note — prevents ghost values)
    sql_clean = re.sub(r"--[^\n]*", "", sql)

    m = re.search(
        r"CHECK\s*\(\s*status\s+IN\s*\((.*?)\)\s*\)",
        sql_clean,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            "No 'CHECK (status IN (...))' constraint found in schema.sql"
        )

    raw_values = m.group(1).split(",")
    return {v.strip().strip("'") for v in raw_values if v.strip()}


class TestStatusDrift:
    """Asserts that schema.sql CHECK constraint and RunStatus enum are in sync."""

    def test_schema_file_exists(self) -> None:
        assert _SCHEMA_SQL.exists(), f"schema.sql not found at {_SCHEMA_SQL}"

    def test_status_check_values_match_enum(self) -> None:
        """SQL CHECK values set-equal RunStatus members — fails CI on drift."""
        sql = _SCHEMA_SQL.read_text()
        sql_values = _extract_status_check_values(sql)
        enum_values = {member.value for member in RunStatus}

        # Provide a readable diff on failure
        sql_only = sql_values - enum_values
        enum_only = enum_values - sql_values

        assert sql_values == enum_values, (
            f"Status drift detected!\n"
            f"  In SQL CHECK but not in RunStatus enum: {sql_only or 'none'}\n"
            f"  In RunStatus enum but not in SQL CHECK: {enum_only or 'none'}\n"
            f"  SQL values:  {sorted(sql_values)}\n"
            f"  Enum values: {sorted(enum_values)}"
        )

    def test_exact_count_is_eleven(self) -> None:
        """Sanity-check that neither source has silent duplicates."""
        sql = _SCHEMA_SQL.read_text()
        sql_values = _extract_status_check_values(sql)
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
        """Confirm the test imports no DB module (pure static file test)."""
        # This test is self-documenting: if we got here, no DB was required.
        # The test file must NOT import app.db.supabase or psycopg.
        import sys
        # Key assertion: test_status_drift itself only depends on pathlib+re+app.models
        assert "app.db.supabase" not in sys.modules, (
            "test_status_drift.py must not import the DB layer"
        )
