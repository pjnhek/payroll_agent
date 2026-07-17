from __future__ import annotations

import importlib.util
import pathlib
from types import ModuleType
from typing import Any

import pytest

from tests.conftest import FakeConnection, FakeTransaction

SCRIPT = pathlib.Path("scripts/migrate_operator_resolution_authority.py")
POSTFLIGHT_FIELDS = (
    "affected_run_count",
    "ambiguous_run_count",
    "winnerless_run_count",
    "multiple_winner_run_count",
    "unclassified_generation_count",
    "remembering_override_count",
    "superseded_authority_count",
    "invalid_supersession_count",
)


def _load_script() -> ModuleType:
    assert SCRIPT.exists(), "operator authority migration script is missing"
    spec = importlib.util.spec_from_file_location("operator_resolution_migration", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TrackingConnection(FakeConnection):
    def __init__(self) -> None:
        super().__init__()
        self.transaction_exited = False

    def transaction(self) -> FakeTransaction:
        outer = self

        class TrackingTransaction(FakeTransaction):
            def __exit__(self, *exc: Any) -> None:
                outer.transaction_exited = True
                return None

        return TrackingTransaction()


def _normalized_sql(conn: FakeConnection) -> list[str]:
    return [" ".join(str(sql).split()).upper() for sql, _ in conn.executed]


def test_fence_close_locks_before_closing_and_enables_trigger(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    conn = TrackingConnection()

    assert module.main(["--fence-writes"], conn=conn) == 0
    sql = _normalized_sql(conn)
    lock_index = next(i for i, stmt in enumerate(sql) if "ACCESS EXCLUSIVE" in stmt)
    table_index = next(
        i
        for i, stmt in enumerate(sql)
        if "CREATE TABLE IF NOT EXISTS OPERATOR_RESOLUTION_WRITER_FENCE" in stmt
    )
    function_index = next(
        i for i, stmt in enumerate(sql) if "CREATE OR REPLACE FUNCTION" in stmt
    )
    trigger_index = next(i for i, stmt in enumerate(sql) if "CREATE TRIGGER" in stmt)
    insert_index = next(
        i
        for i, stmt in enumerate(sql)
        if "INSERT INTO OPERATOR_RESOLUTION_WRITER_FENCE" in stmt
    )
    close_index = next(
        i
        for i, stmt in enumerate(sql)
        if "UPDATE OPERATOR_RESOLUTION_WRITER_FENCE" in stmt
    )
    enable_index = next(i for i, stmt in enumerate(sql) if "ENABLE TRIGGER" in stmt)
    assert (
        lock_index
        < table_index
        < function_index
        < trigger_index
        < insert_index
        < close_index
        < enable_index
    )
    assert "WRITES_OPEN) VALUES (TRUE, FALSE)" in sql[insert_index]
    assert conn.transaction_exited
    assert capsys.readouterr().out == "writer_fence=closed\n"


def test_fence_install_failure_rolls_back_without_reporting_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    class RollbackConnection(FakeConnection):
        rolled_back = False

        def transaction(self) -> FakeTransaction:
            outer = self

            class RollbackTransaction(FakeTransaction):
                def __exit__(self, exc_type: Any, *exc: Any) -> None:
                    outer.rolled_back = exc_type is not None
                    return None

            return RollbackTransaction()

        def execute(self, sql: str, params: Any = None) -> Any:
            if "CREATE OR REPLACE FUNCTION" in sql:
                raise RuntimeError("simulated fence install failure")
            self.executed.append((sql, params))
            return self

    conn = RollbackConnection()

    assert module.main(["--fence-writes"], conn=conn) == 2
    sql = _normalized_sql(conn)
    assert any("ACCESS EXCLUSIVE" in stmt for stmt in sql)
    assert any(
        "CREATE TABLE IF NOT EXISTS OPERATOR_RESOLUTION_WRITER_FENCE" in stmt
        for stmt in sql
    )
    assert not any("WRITES_OPEN = FALSE" in stmt for stmt in sql)
    assert conn.rolled_back
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_schema_trigger_rejects_parent_insert_while_closed() -> None:
    schema = pathlib.Path("app/db/schema.sql").read_text()
    function_body = schema.split(
        "CREATE OR REPLACE FUNCTION enforce_operator_resolution_writer_fence", 1
    )[1].split("$$;", 1)[0]
    assert "writes_open IS TRUE" in function_body
    assert "RAISE EXCEPTION" in function_body
    assert "BEFORE INSERT ON operator_resume_resolutions" in schema


def test_ambiguous_migration_aborts_before_any_authority_write(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((2, 0, 1))

    assert module.main(["--migrate-authority"], conn=conn) == 1
    sql = _normalized_sql(conn)
    assert any("FOR UPDATE" in stmt for stmt in sql)
    assert not any("SET AUTHORITATIVE" in stmt for stmt in sql)
    assert not any("SET REMEMBER" in stmt for stmt in sql)
    assert capsys.readouterr().out == ""


def test_sole_generation_migration_sets_winner_and_forces_remember_false(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((3, 2, 0))
    conn.script_fetchone((2, 0, 0, 0, 0, 0, 0, 0))

    assert module.main(["--migrate-authority"], conn=conn) == 0
    sql = _normalized_sql(conn)
    authority = next(stmt for stmt in sql if "SET AUTHORITATIVE" in stmt)
    remember = next(stmt for stmt in sql if "SET REMEMBER" in stmt)
    assert "AUTHORITATIVE = TRUE" in authority
    assert "SUPERSEDED_BY = NULL" in authority
    assert "GENERATION_COUNT = 1" in authority
    assert "REMEMBER = FALSE" in remember
    assert "CREATED_AT" not in " ".join(sql)
    assert "ORDER BY" not in " ".join(sql)
    assert capsys.readouterr().out.splitlines() == [
        f"{field}={value}"
        for field, value in zip(
            POSTFLIGHT_FIELDS, (2, 0, 0, 0, 0, 0, 0, 0), strict=True
        )
    ]


@pytest.mark.parametrize(
    "postflight",
    [
        (2, 0, 1, 0, 1, 0, 0, 0),
        (2, 0, 0, 1, 0, 0, 0, 0),
        (2, 1, 0, 0, 0, 0, 0, 0),
        (2, 0, 0, 0, 0, 1, 0, 0),
        (2, 0, 0, 0, 0, 0, 1, 0),
        (2, 0, 0, 0, 0, 0, 0, 1),
    ],
)
def test_postflight_fails_closed_without_pii(
    postflight: tuple[int, ...],
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone(postflight)

    assert module.main(["--check"], conn=conn) == 1
    output = capsys.readouterr().out
    assert output.splitlines() == [
        f"{field}={value}"
        for field, value in zip(POSTFLIGHT_FIELDS, postflight, strict=True)
    ]
    for forbidden in ("run_id", "submitted_name", "employee_id", "mapping"):
        assert forbidden not in output.lower()


def test_fresh_or_zero_generation_database_passes_without_writes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((0, 0, 0, 0, 0, 0, 0, 0))

    assert module.main(["--check"], conn=conn) == 0
    assert len(conn.executed) == 1
    assert not any(
        token in _normalized_sql(conn)[0] for token in ("INSERT ", "UPDATE ", "DELETE ")
    )
    assert capsys.readouterr().out.endswith("invalid_supersession_count=0\n")


def test_postflight_sql_validates_remember_and_supersession_relationships() -> None:
    module = _load_script()
    sql = " ".join(module._POSTFLIGHT_SQL.split()).upper()

    assert "O.REMEMBER IS TRUE" in sql
    assert "R.AUTHORITATIVE AND R.SUPERSEDED_BY IS NOT NULL" in sql
    assert "WINNER.ID = LOSER.SUPERSEDED_BY" in sql
    assert "WINNER.RUN_ID = LOSER.RUN_ID" in sql
    assert "WINNER.AUTHORITATIVE" in sql
    assert "NOT LOSER.AUTHORITATIVE" in sql
    assert "WINNER.ID IS NULL" in sql


@pytest.mark.parametrize(
    "postflight",
    [
        (1, 0, 0, 0, 0, 1, 0, 0),
        (1, 0, 0, 0, 0, 0, 1, 0),
        (1, 0, 0, 0, 0, 0, 0, 1),
    ],
)
def test_reopen_rejects_invalid_authority_relationships(
    postflight: tuple[int, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((False, "O", True, True))
    conn.script_fetchone(postflight)
    monkeypatch.setattr(
        module,
        "diff_against_live",
        lambda _conn: type("Diff", (), {"is_in_sync": True})(),
    )

    argv = [
        "--reopen-writes",
        "--deployed-revision",
        "a" * 40,
        "--schema-verified",
        "--authority-verified",
    ]
    assert module.main(argv, conn=conn) == 2
    assert not any("WRITES_OPEN = TRUE" in stmt for stmt in _normalized_sql(conn))


@pytest.mark.parametrize(
    "argv",
    [
        ["--reopen-writes"],
        ["--reopen-writes", "--deployed-revision", "abc1234"],
        ["--reopen-writes", "--deployed-revision", "abcdef1234567890"],
        ["--reopen-writes", "--deployed-revision", "a" * 39],
        ["--reopen-writes", "--deployed-revision", "a" * 41],
        ["--reopen-writes", "--deployed-revision", "A" * 40],
        [
            "--reopen-writes",
            "--deployed-revision",
            "not-a-revision",
            "--schema-verified",
            "--authority-verified",
        ],
    ],
)
def test_reopen_requires_exact_verified_inputs_and_leaves_fence_closed(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    conn = FakeConnection()

    assert module.main(argv, conn=conn) == 2
    assert not any(
        "WRITES_OPEN = TRUE" in stmt for stmt in _normalized_sql(conn)
    )
    assert capsys.readouterr().out == ""


def test_reopen_rechecks_schema_fence_and_authority_before_open(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load_script()
    conn = FakeConnection()
    conn.script_fetchone((False, "O", True, True))
    conn.script_fetchone((2, 0, 0, 0, 0, 0, 0, 0))
    monkeypatch.setattr(
        module,
        "diff_against_live",
        lambda _conn: type("Diff", (), {"is_in_sync": True})(),
    )

    argv = [
        "--reopen-writes",
        "--deployed-revision",
        "abcdef1234567890abcdef1234567890abcdef12",
        "--schema-verified",
        "--authority-verified",
    ]
    assert module.main(argv, conn=conn) == 0
    sql = _normalized_sql(conn)
    lock_index = next(i for i, stmt in enumerate(sql) if "ACCESS EXCLUSIVE" in stmt)
    open_index = next(i for i, stmt in enumerate(sql) if "WRITES_OPEN = TRUE" in stmt)
    assert lock_index < open_index
    assert capsys.readouterr().out.splitlines() == [
        "writer_fence=open",
        "deployed_revision=abcdef1234567890abcdef1234567890abcdef12",
    ]


def test_database_failures_are_silent_and_never_open(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    class BrokenConnection:
        def transaction(self) -> FakeTransaction:
            return FakeTransaction()

        def execute(self, sql: str, params: Any = None) -> Any:
            raise RuntimeError("employee mapping: pii")

    assert module.main(["--fence-writes"], conn=BrokenConnection()) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
