from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType
from typing import Any

import pytest

from tests.conftest import FakeConnection

SCRIPT = pathlib.Path("scripts/check_operator_resolution_inventory.py")
EXPECTED_FIELDS = (
    "unresolved_run_count",
    "single_generation_run_count",
    "ambiguous_run_count",
)


def _load_script() -> ModuleType:
    assert SCRIPT.exists(), "operator-resolution inventory script is missing"
    spec = importlib.util.spec_from_file_location("operator_resolution_inventory", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("row", "expected_exit"),
    [
        ((0, 0, 0), 0),
        ((3, 3, 0), 0),
        ((4, 3, 1), 1),
    ],
)
def test_inventory_exact_aggregate_output_and_fail_closed(
    row: tuple[int, int, int], expected_exit: int, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone(row)

    assert module.main(conn=conn) == expected_exit
    assert capsys.readouterr().out.splitlines() == [
        f"{field}={value}" for field, value in zip(EXPECTED_FIELDS, row, strict=True)
    ]


def test_inventory_query_is_read_only_grouped_and_uses_no_order_proxy() -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((2, 1, 1))

    assert module.main(conn=conn) == 1
    assert len(conn.executed) == 1
    sql = " ".join(str(conn.executed[0][0]).split()).upper()
    assert "OPERATOR_RESUME_RESOLUTIONS" in sql
    assert "PAYROLL_RUNS" in sql
    assert "GROUP BY" in sql
    assert "STATUS = 'NEEDS_OPERATOR'" in sql
    assert "INSERT " not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "ORDER BY" not in sql
    assert "CREATED_AT" not in sql


def test_inventory_output_is_pii_safe(capsys: pytest.CaptureFixture[str]) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((9, 8, 1))

    module.main(conn=conn)
    output = capsys.readouterr().out
    assert tuple(line.split("=", 1)[0] for line in output.splitlines()) == EXPECTED_FIELDS
    for forbidden in (
        "run_id",
        "submitted_name",
        "employee_id",
        "mapping",
        "exception",
        "error",
        "traceback",
    ):
        assert forbidden not in output.lower()


def test_inventory_database_failure_is_silent_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()

    class BrokenConnection:
        def execute(self, sql: str, params: Any = None) -> Any:
            raise RuntimeError("pii: employee mapping leaked")

    assert module.main(conn=BrokenConnection()) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
