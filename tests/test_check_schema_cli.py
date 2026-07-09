import contextlib
from unittest.mock import patch

from app.db.check_schema import main
from app.db.schema_introspect import SchemaDiff
from tests.conftest import FakeConnection


@contextlib.contextmanager
def _cm(conn):
    yield conn


def test_main_exits_0_in_sync(capsys):
    with patch("app.db.check_schema.get_connection", lambda: _cm(FakeConnection())), \
         patch("app.db.check_schema.diff_against_live", return_value=SchemaDiff({}, [], [], [])):
        assert main() == 0
    assert "in_sync" in capsys.readouterr().out


def test_main_exits_1_on_drift(capsys):
    diff = SchemaDiff({"payroll_runs": ["clarification_round"]}, [], [], [])
    with patch("app.db.check_schema.get_connection", lambda: _cm(FakeConnection())), \
         patch("app.db.check_schema.diff_against_live", return_value=diff):
        assert main() == 1
    assert "clarification_round" in capsys.readouterr().out
