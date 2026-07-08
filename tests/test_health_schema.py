from unittest.mock import patch
import contextlib
from fastapi.testclient import TestClient

from app.main import app
from app.db.schema_introspect import SchemaDiff
from tests.conftest import FakeConnection

client = TestClient(app)


@contextlib.contextmanager
def _fake_conn_cm(conn):
    yield conn


def test_health_schema_in_sync_returns_200():
    diff = SchemaDiff({}, [], [], [])  # nothing missing
    with patch("app.main.get_connection", lambda: _fake_conn_cm(FakeConnection())), \
         patch("app.main.diff_against_live", return_value=diff):
        r = client.get("/health/schema")
    assert r.status_code == 200
    assert r.json() == {"status": "in_sync"}


def test_health_schema_drift_returns_503_with_missing():
    diff = SchemaDiff({"payroll_runs": ["clarification_round"]}, ["needs_operator"], [], [])
    with patch("app.main.get_connection", lambda: _fake_conn_cm(FakeConnection())), \
         patch("app.main.diff_against_live", return_value=diff):
        r = client.get("/health/schema")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "drift"
    assert body["missing"]["payroll_runs"] == ["clarification_round"]
    assert body["missing"]["status_values"] == ["needs_operator"]


def test_health_schema_db_error_returns_503_no_leak():
    def _boom():
        raise RuntimeError("postgresql://user:secret@host/db unreachable")
    with patch("app.main.get_connection", _boom):
        r = client.get("/health/schema")
    assert r.status_code == 503
    assert "secret" not in r.text and "postgresql://" not in r.text
