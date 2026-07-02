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


def _extract_do_block_status_values(sql: str) -> set[str]:
    """Parse the value set out of the payroll_runs_status_check DO-block re-add.

    Review fix (codex MEDIUM #5): `_extract_check_in_values` uses `re.search`,
    which only ever finds the FIRST `CHECK (status IN (...))` match in the whole
    file — the INLINE CREATE TABLE CHECK. It structurally cannot see the DO-block's
    re-add value list below it. This is a SEPARATE, dedicated parser: it locates
    the `payroll_runs_status_check` constraint-name literal first, then searches
    for the `CHECK (status IN (...))` that appears AFTER that point in the file
    (the DO-block's ADD CONSTRAINT), independent of the inline-CHECK parser.
    """
    sql_clean = re.sub(r"--[^\n]*", "", sql)

    marker = "payroll_runs_status_check"
    marker_idx = sql_clean.find(marker)
    if marker_idx == -1:
        raise ValueError(
            "No 'payroll_runs_status_check' constraint name found in schema.sql"
        )
    # Search for the CHECK (status IN (...)) that appears after the constraint
    # name literal — the DO-block's ADD CONSTRAINT clause, not the inline CHECK.
    remainder = sql_clean[marker_idx:]
    m = re.search(
        r"CHECK\s*\(\s*status\s+IN\s*\((.*?)\)\s*\)",
        remainder,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        raise ValueError(
            "No 'CHECK (status IN (...))' found after payroll_runs_status_check "
            "in schema.sql (DO-block re-add value list not found)"
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

    def test_status_exact_count_is_ten(self) -> None:
        """Sanity-check that neither status source has silent duplicates."""
        sql = _SCHEMA_SQL.read_text()
        sql_values = _extract_check_in_values(sql, "status")
        enum_values = {member.value for member in RunStatus}

        assert len(sql_values) == 10, (
            f"Expected 10 unique status values in SQL CHECK, got {len(sql_values)}: "
            f"{sorted(sql_values)}"
        )
        assert len(enum_values) == 10, (
            f"Expected 10 RunStatus members, got {len(enum_values)}: "
            f"{sorted(enum_values)}"
        )

    def test_do_block_status_check_matches_enum(self) -> None:
        """The DO-block's payroll_runs_status_check re-add list matches RunStatus.

        Review fix (codex MEDIUM #5): independent of `_extract_check_in_values`
        (which only ever sees the FIRST CHECK match, i.e. the inline CREATE TABLE
        CHECK). This test uses the dedicated `_extract_do_block_status_values`
        parser so a stale value in EITHER the inline CHECK or the DO-block re-add
        list fails CI — a one-sided edit to either location is now caught.
        """
        sql = _SCHEMA_SQL.read_text()
        do_block_values = _extract_do_block_status_values(sql)
        enum_values = {member.value for member in RunStatus}

        assert do_block_values == enum_values, (
            "Enum drift detected in the payroll_runs_status_check DO-block re-add "
            "list!\n"
            f"  In DO-block but not in Python: {do_block_values - enum_values or 'none'}\n"
            f"  In Python but not in DO-block: {enum_values - do_block_values or 'none'}\n"
            f"  DO-block values: {sorted(do_block_values)}\n"
            f"  Python values:   {sorted(enum_values)}"
        )

    def test_needs_clarification_absent_file_wide(self) -> None:
        """'needs_clarification' has zero occurrences anywhere in schema.sql.

        Belt-and-suspenders proof (review fix, folded todo 260623-06) that the
        removed status value is gone from every location — inline CHECK, DO-block
        re-add list, and any stray comment — not just the two CHECK definitions.
        """
        sql = _SCHEMA_SQL.read_text()
        assert "needs_clarification" not in sql, (
            "'needs_clarification' still appears in schema.sql — it must be fully "
            "removed (folded todo 260623-06)"
        )

    def test_do_block_constraint_drops_are_column_anchored(self) -> None:
        """WR-06 (phase-8 review): DO-block DROPs must be column-anchored, not name-fuzzy.

        The old idiom — `SELECT conname INTO _con_name ... WHERE conname LIKE
        '%status%'` (and the mirrored '%purpose%' block) — silently took one
        arbitrary matching row (no STRICT) and would DROP-and-never-restore any
        unrelated future constraint whose NAME merely contained the substring.
        The fixed blocks select CHECK constraints by their actual column set
        (conkey -> pg_attribute) instead. This static guard pins the idiom so a
        future schema edit cannot reintroduce a name-substring DROP.
        """
        # Strip line comments first (same normalization the value-set parsers
        # use) — the WR-06 explanatory comments legitimately mention the old
        # idiom; only EXECUTABLE SQL must be free of it.
        sql = re.sub(r"--[^\n]*", "", _SCHEMA_SQL.read_text())
        assert "conname LIKE" not in sql, (
            "schema.sql must never DROP a constraint matched by a name substring "
            "(conname LIKE) — anchor on the constraint's column set via conkey "
            "instead (WR-06)"
        )
        # Both migration DO-blocks (payroll_runs.status, email_messages.purpose)
        # must use the conkey-anchored matcher.
        assert sql.count("ANY (c.conkey)") == 2, (
            "expected exactly 2 conkey-anchored constraint matchers (the status "
            "and purpose DO-blocks); update this count only alongside a reviewed "
            "new migration block (WR-06)"
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


class TestIndexStaticGuard:
    """D-8-10 static half of the hot-path index guard (the live half is 08-03).

    Mirrors TestEnumCheckDrift's parse-and-assert shape: purely textual assertions
    against schema.sql, no DB connection.  Proves the 3 OPS2-02 CREATE INDEX
    statements exist with their exact researched column order, and that
    businesses.contact_email / uq_email_run_purpose coverage facts still hold
    (the substitute proof for D-8-09's non-duplication decision).
    """

    def test_schema_file_exists(self) -> None:
        assert _SCHEMA_SQL.exists(), f"schema.sql not found at {_SCHEMA_SQL}"

    def test_email_messages_composite_index_present(self) -> None:
        sql = _SCHEMA_SQL.read_text()
        assert (
            "CREATE INDEX IF NOT EXISTS idx_email_messages_run_direction_state"
            in sql
        ), "idx_email_messages_run_direction_state statement not found"
        # Column order is locked by D-8-09 / 08-RESEARCH.md Pattern 3.
        m = re.search(
            r"idx_email_messages_run_direction_state\s*\n?\s*ON\s+email_messages\s*\(([^)]*)\)",
            sql,
        )
        assert m, "could not find the index's ON email_messages (...) column list"
        columns = [c.strip() for c in m.group(1).split(",")]
        assert columns == ["run_id", "direction", "send_state"], (
            f"expected column order (run_id, direction, send_state), got {columns}"
        )

    def test_payroll_runs_created_at_index_present(self) -> None:
        sql = _SCHEMA_SQL.read_text()
        assert (
            "CREATE INDEX IF NOT EXISTS idx_payroll_runs_created_at" in sql
        ), "idx_payroll_runs_created_at statement not found"
        m = re.search(
            r"idx_payroll_runs_created_at\s*\n?\s*ON\s+payroll_runs\s*\(([^)]*)\)",
            sql,
        )
        assert m, "could not find the index's ON payroll_runs (...) column list"
        assert m.group(1).strip().lower() == "created_at desc", (
            f"expected 'created_at DESC', got {m.group(1).strip()!r}"
        )

    def test_payroll_runs_status_index_present(self) -> None:
        sql = _SCHEMA_SQL.read_text()
        assert (
            "CREATE INDEX IF NOT EXISTS idx_payroll_runs_status" in sql
        ), "idx_payroll_runs_status statement not found"
        m = re.search(
            r"idx_payroll_runs_status\s*\n?\s*ON\s+payroll_runs\s*\(([^)]*)\)",
            sql,
        )
        assert m, "could not find the index's ON payroll_runs (...) column list"
        assert m.group(1).strip() == "status", (
            f"expected 'status', got {m.group(1).strip()!r}"
        )

    def test_exactly_three_new_indexes(self) -> None:
        sql = _SCHEMA_SQL.read_text()
        assert sql.count("CREATE INDEX IF NOT EXISTS") == 3, (
            "expected exactly 3 CREATE INDEX IF NOT EXISTS statements in schema.sql"
        )

    def test_contact_email_still_not_null_unique(self) -> None:
        """D-8-09 substitute proof: contact_email's UNIQUE constraint is untouched.

        No separate CREATE INDEX on businesses(contact_email) should ever exist —
        the NOT NULL UNIQUE constraint's implicit index already covers it.
        """
        sql = _SCHEMA_SQL.read_text()
        m = re.search(r"contact_email\s+TEXT\s+NOT NULL UNIQUE", sql)
        assert m, "businesses.contact_email must remain NOT NULL UNIQUE"
        assert not re.search(
            r"CREATE INDEX[^\n]*\n?\s*ON\s+businesses\s*\(\s*contact_email\s*\)",
            sql,
            re.IGNORECASE,
        ), "a duplicate index on businesses(contact_email) must not exist (D-8-09)"

    def test_uq_email_run_purpose_still_present(self) -> None:
        sql = _SCHEMA_SQL.read_text()
        assert "uq_email_run_purpose" in sql, (
            "uq_email_run_purpose constraint must still be present"
        )

    def test_no_db_connection_needed(self) -> None:
        """Confirm this file imports no DB module (pure static file test).

        Copied verbatim (per-class, since pytest classes don't inherit test
        collection across classes) from TestEnumCheckDrift.test_no_db_connection_needed
        so this class is provably hermetic like its sibling.
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
